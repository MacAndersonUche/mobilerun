"""Per-app + version_code selector cache — local disk + DynamoDB sync."""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from mobilerun.selectors.models import (
    DEFAULT_SELECTORS,
    CachedEntry,
    CacheStatus,
    ElementRole,
    SelectorSpec,
)

log = logging.getLogger("mobilerun.selectors.cache")


def _data_root() -> Path:
    root = Path(os.environ.get("MOBILERUN_DATA", Path.home() / ".mobilerun"))
    root.mkdir(parents=True, exist_ok=True)
    return root / "selector_cache"


class SelectorCache:
    """
    Keys: package_name + version_code → role → CachedEntry.

    Local JSON is source of truth on device; DynamoDB mirrors for multi-device.
    """

    def __init__(
        self,
        *,
        user_id: str = "local",
        persist_dir: Optional[Path] = None,
        max_rediscovery: int = 3,
    ):
        self.user_id = user_id
        self.persist_dir = persist_dir or _data_root()
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.max_rediscovery = max_rediscovery
        # {(package, version): {role: CachedEntry}}
        self._mem: Dict[str, Dict[str, CachedEntry]] = {}
        self._llm_totals: Dict[str, int] = {}

    def _key(self, package_name: str, version_code: str) -> str:
        return f"{package_name}@{version_code or '0'}"

    def _path(self, package_name: str, version_code: str) -> Path:
        safe = self._key(package_name, version_code).replace("/", "_")
        return self.persist_dir / f"{safe}.json"

    def load(self, package_name: str, version_code: str) -> Dict[str, CachedEntry]:
        k = self._key(package_name, version_code)
        if k in self._mem:
            return self._mem[k]

        entries: Dict[str, CachedEntry] = {}
        path = self._path(package_name, version_code)
        if path.exists():
            try:
                raw = json.loads(path.read_text())
                for role, data in (raw.get("roles") or {}).items():
                    entries[role] = CachedEntry.from_dict(data)
                self._llm_totals[k] = int(raw.get("total_llm_calls") or 0)
            except Exception:
                log.exception("failed reading selector cache %s", path)

        # Seed defaults for known packages if empty
        if not entries:
            defaults = (
                DEFAULT_SELECTORS.get(f"{package_name}@{version_code}")
                or DEFAULT_SELECTORS.get(package_name)
                or {}
            )
            for role, spec in defaults.items():
                entries[role] = CachedEntry(
                    role=role,
                    selector=spec,
                    package_name=package_name,
                    version_code=str(version_code),
                    source="heuristic",
                    llm_calls=0,
                )

        # Try DynamoDB overlay
        remote = self._load_remote(package_name, version_code)
        if remote:
            for role, entry in remote.items():
                # Remote LLM-discovered wins over heuristic seed
                if role not in entries or entry.source == "llm":
                    entries[role] = entry

        self._mem[k] = entries
        return entries

    def get(
        self, package_name: str, version_code: str, role: str
    ) -> Optional[CachedEntry]:
        return self.load(package_name, version_code).get(role)

    def put(self, entry: CachedEntry) -> None:
        k = self._key(entry.package_name, entry.version_code)
        roles = self.load(entry.package_name, entry.version_code)
        roles[entry.role] = entry
        self._mem[k] = roles
        if entry.llm_calls:
            self._llm_totals[k] = self._llm_totals.get(k, 0) + max(
                0, entry.llm_calls - (roles.get(entry.role).llm_calls if False else 0)
            )
        self._persist(entry.package_name, entry.version_code)
        self._save_remote(entry.package_name, entry.version_code)

    def mark_success(self, package_name: str, version_code: str, role: str) -> None:
        entry = self.get(package_name, version_code, role)
        if not entry:
            return
        from datetime import datetime

        entry.last_success_at = datetime.now().isoformat()
        self.put(entry)

    def mark_failure(
        self, package_name: str, version_code: str, role: str
    ) -> CachedEntry:
        from datetime import datetime

        entry = self.get(package_name, version_code, role)
        if not entry:
            entry = CachedEntry(
                role=role,
                selector=SelectorSpec(),
                package_name=package_name,
                version_code=str(version_code),
            )
        entry.last_failure_at = datetime.now().isoformat()
        entry.rediscovery_attempts += 1
        self.put(entry)
        return entry

    def invalidate(
        self, package_name: str, version_code: str, role: Optional[str] = None
    ) -> None:
        k = self._key(package_name, version_code)
        roles = self.load(package_name, version_code)
        if role:
            roles.pop(role, None)
        else:
            roles.clear()
        self._mem[k] = roles
        self._persist(package_name, version_code)
        self._save_remote(package_name, version_code)

    def invalidate_if_version_changed(
        self, package_name: str, old_version: str, new_version: str
    ) -> bool:
        if str(old_version) == str(new_version):
            return False
        # Drop old version cache from memory; new version starts fresh (defaults)
        old_k = self._key(package_name, old_version)
        self._mem.pop(old_k, None)
        return True

    def status(self, package_name: str, version_code: str) -> CacheStatus:
        roles = self.load(package_name, version_code)
        k = self._key(package_name, version_code)
        role_rows = []
        last = None
        total_llm = self._llm_totals.get(k, 0)
        for role, e in roles.items():
            role_rows.append(
                {
                    "role": role,
                    "selector": e.selector.to_dict(),
                    "discovered_at": e.discovered_at,
                    "llm_calls": e.llm_calls,
                    "rediscovery_attempts": e.rediscovery_attempts,
                    "source": e.source,
                    "last_success_at": e.last_success_at,
                    "last_failure_at": e.last_failure_at,
                    "version_code": e.version_code,
                }
            )
            total_llm = max(total_llm, e.llm_calls)
            if e.discovered_at and (last is None or e.discovered_at > last):
                last = e.discovered_at
        return CacheStatus(
            package_name=package_name,
            version_code=str(version_code),
            roles=role_rows,
            total_llm_calls=total_llm,
            last_discovered_at=last,
        )

    def list_packages(self) -> List[CacheStatus]:
        seen = set()
        out = []
        for path in self.persist_dir.glob("*.json"):
            try:
                raw = json.loads(path.read_text())
                pkg = raw.get("package_name")
                ver = raw.get("version_code")
                if pkg is None:
                    continue
                key = (pkg, str(ver))
                if key in seen:
                    continue
                seen.add(key)
                out.append(self.status(pkg, str(ver)))
            except Exception:
                continue
        # Also include in-memory packages
        for k, roles in self._mem.items():
            if not roles:
                continue
            e = next(iter(roles.values()))
            key = (e.package_name, e.version_code)
            if key in seen:
                continue
            seen.add(key)
            out.append(self.status(e.package_name, e.version_code))
        return out

    def _persist(self, package_name: str, version_code: str) -> None:
        k = self._key(package_name, version_code)
        roles = self._mem.get(k) or {}
        path = self._path(package_name, version_code)
        payload = {
            "package_name": package_name,
            "version_code": str(version_code),
            "updated_at": int(time.time()),
            "total_llm_calls": self._llm_totals.get(k, 0),
            "roles": {r: e.to_dict() for r, e in roles.items()},
        }
        path.write_text(json.dumps(payload, indent=2))

    def _load_remote(
        self, package_name: str, version_code: str
    ) -> Dict[str, CachedEntry]:
        try:
            from storage import get_user_setting
        except ImportError:
            try:
                from backend.storage import get_user_setting  # type: ignore
            except ImportError:
                return {}
        try:
            data = get_user_setting(
                self.user_id, f"selectors:{package_name}:{version_code}"
            )
            if not data:
                return {}
            return {
                role: CachedEntry.from_dict(d)
                for role, d in (data.get("roles") or {}).items()
            }
        except Exception:
            return {}

    def _save_remote(self, package_name: str, version_code: str) -> None:
        try:
            from storage import save_user_setting
        except ImportError:
            try:
                from backend.storage import save_user_setting  # type: ignore
            except ImportError:
                return
        try:
            k = self._key(package_name, version_code)
            roles = self._mem.get(k) or {}
            save_user_setting(
                self.user_id,
                f"selectors:{package_name}:{version_code}",
                {
                    "package_name": package_name,
                    "version_code": str(version_code),
                    "total_llm_calls": self._llm_totals.get(k, 0),
                    "roles": {r: e.to_dict() for r, e in roles.items()},
                },
            )
        except Exception:
            log.debug("selector DynamoDB sync skipped", exc_info=True)

    def record_llm_call(self, package_name: str, version_code: str) -> None:
        k = self._key(package_name, version_code)
        self._llm_totals[k] = self._llm_totals.get(k, 0) + 1
