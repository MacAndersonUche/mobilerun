"""Per-app + version_code selector cache — local disk + DynamoDB sync.

Stores multiple layout variants per role (default cap 4, min 2). Variants are
tried in success-rate order; least-used are evicted when over cap.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from mobilerun.selectors.models import (
    DEFAULT_MAX_LAYOUT_VARIANTS,
    DEFAULT_SELECTORS,
    CachedEntry,
    CacheStatus,
    LayoutVariant,
    SelectorSpec,
    clamp_max_variants,
)

log = logging.getLogger("mobilerun.selectors.cache")


def _data_root() -> Path:
    # Lambda only allows writes under /tmp; Path.home() is often read-only.
    candidates = []
    if os.environ.get("MOBILERUN_DATA"):
        candidates.append(Path(os.environ["MOBILERUN_DATA"]))
    candidates.append(Path("/tmp/mobilerun"))
    candidates.append(Path.home() / ".mobilerun")
    last_err: Optional[Exception] = None
    for root in candidates:
        try:
            root.mkdir(parents=True, exist_ok=True)
            return root / "selector_cache"
        except OSError as e:
            last_err = e
            continue
    raise RuntimeError(f"No writable MOBILERUN_DATA path: {last_err}")


def _aws_storage() -> bool:
    return os.environ.get("USE_AWS_STORAGE", "").lower() in ("1", "true", "yes")


def _storage_get():
    try:
        from storage import get_user_setting, save_user_setting

        return get_user_setting, save_user_setting
    except ImportError:
        try:
            from backend.storage import (  # type: ignore
                get_user_setting,
                save_user_setting,
            )

            return get_user_setting, save_user_setting
        except ImportError:
            return None, None


class SelectorCache:
    """
    Keys: package_name + version_code → role → CachedEntry (with variants).

    On AWS (USE_AWS_STORAGE): DynamoDB is the source of truth; /tmp (or
    MOBILERUN_DATA) is a best-effort read-through cache only.
    Locally: JSON under MOBILERUN_DATA / ~/.mobilerun is authoritative.
    """

    INDEX_SETTING = "selectors_index"

    def __init__(
        self,
        *,
        user_id: str = "local",
        persist_dir: Optional[Path] = None,
        max_rediscovery: int = 3,
        max_layout_variants: Optional[int] = None,
    ):
        self.user_id = user_id
        self.persist_dir = persist_dir or _data_root()
        try:
            self.persist_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            # Still usable via Dynamo / memory when disk is unavailable
            log.warning("selector cache dir not writable: %s", self.persist_dir)
        self.max_rediscovery = max_rediscovery
        env_cap = os.environ.get("MOBILERUN_MAX_LAYOUT_VARIANTS")
        if max_layout_variants is None and env_cap:
            try:
                max_layout_variants = int(env_cap)
            except ValueError:
                max_layout_variants = None
        self.max_layout_variants = clamp_max_variants(
            max_layout_variants
            if max_layout_variants is not None
            else DEFAULT_MAX_LAYOUT_VARIANTS
        )
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
        remote_meta: Dict[str, Any] = {}

        # Dynamo first when AWS; then local read-through cache
        if _aws_storage():
            remote, remote_meta = self._load_remote_full(package_name, version_code)
            for role, entry in remote.items():
                entries[role] = entry
            if remote_meta.get("total_llm_calls") is not None:
                self._llm_totals[k] = int(remote_meta["total_llm_calls"])

        path = self._path(package_name, version_code)
        local_entries: Dict[str, CachedEntry] = {}
        if path.exists():
            try:
                raw = json.loads(path.read_text())
                for role, data in (raw.get("roles") or {}).items():
                    local_entries[role] = CachedEntry.from_dict(data)
                if k not in self._llm_totals:
                    self._llm_totals[k] = int(raw.get("total_llm_calls") or 0)
            except Exception:
                log.exception("failed reading selector cache %s", path)

        if not _aws_storage():
            entries = local_entries
        else:
            # Fill gaps from local cache only when Dynamo had nothing for a role
            for role, entry in local_entries.items():
                if role not in entries:
                    entries[role] = entry

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
                    variants=[
                        LayoutVariant(
                            selector=spec,
                            source="heuristic",
                            label=str(version_code),
                        )
                    ],
                )

        # Non-AWS: overlay Dynamo if present (multi-device laptop sync)
        if not _aws_storage():
            remote, remote_meta = self._load_remote_full(package_name, version_code)
            for role, entry in remote.items():
                if role not in entries or entry.source == "llm" or entry.variants:
                    entries[role] = entry
            if remote_meta.get("total_llm_calls") is not None:
                self._llm_totals[k] = max(
                    self._llm_totals.get(k, 0), int(remote_meta["total_llm_calls"])
                )

        for e in entries.values():
            e.ensure_variants()

        self._mem[k] = entries
        # Warm /tmp read-through when we hydrated from Dynamo
        if _aws_storage() and entries:
            self._persist_local(package_name, version_code)
        return entries

    def get(
        self, package_name: str, version_code: str, role: str
    ) -> Optional[CachedEntry]:
        entry = self.load(package_name, version_code).get(role)
        if entry:
            entry.ensure_variants()
        return entry

    def put(self, entry: CachedEntry) -> None:
        entry.ensure_variants()
        k = self._key(entry.package_name, entry.version_code)
        roles = self.load(entry.package_name, entry.version_code)
        roles[entry.role] = entry
        self._mem[k] = roles
        self._persist(entry.package_name, entry.version_code)

    def ordered_variants(
        self, package_name: str, version_code: str, role: str
    ) -> List[LayoutVariant]:
        entry = self.get(package_name, version_code, role)
        if not entry:
            return []
        return entry.ordered_variants()

    def mark_variant_success(
        self,
        package_name: str,
        version_code: str,
        role: str,
        variant_id: str,
    ) -> Optional[CachedEntry]:
        entry = self.get(package_name, version_code, role)
        if not entry:
            return None
        now = datetime.now().isoformat()
        for v in entry.variants:
            if v.id == variant_id:
                v.hits += 1
                v.last_success_at = now
                break
        entry.last_success_at = now
        self.put(entry)
        return entry

    def mark_variant_miss(
        self,
        package_name: str,
        version_code: str,
        role: str,
        variant_id: str,
    ) -> Optional[CachedEntry]:
        entry = self.get(package_name, version_code, role)
        if not entry:
            return None
        now = datetime.now().isoformat()
        for v in entry.variants:
            if v.id == variant_id:
                v.misses += 1
                v.last_failure_at = now
                break
        entry.last_failure_at = now
        self.put(entry)
        return entry

    def mark_success(self, package_name: str, version_code: str, role: str) -> None:
        """Legacy: bump best / first variant."""
        entry = self.get(package_name, version_code, role)
        if not entry or not entry.variants:
            return
        best = entry.ordered_variants()[0]
        self.mark_variant_success(package_name, version_code, role, best.id)

    def mark_failure(
        self, package_name: str, version_code: str, role: str
    ) -> CachedEntry:
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

    def add_variant(
        self,
        *,
        package_name: str,
        version_code: str,
        role: str,
        selector: SelectorSpec,
        source: str = "llm",
        nav_path: Optional[List[Dict[str, Any]]] = None,
        label: str = "",
        llm_calls: int = 0,
        rediscovery_attempts: Optional[int] = None,
    ) -> Tuple[CachedEntry, LayoutVariant, Optional[LayoutVariant]]:
        """
        Add a layout variant. If an equivalent selector exists, refresh it.
        If over ``max_layout_variants``, evict the least-used variant.

        Returns (entry, variant, evicted_or_None).
        """
        entry = self.get(package_name, version_code, role)
        if entry is None:
            entry = CachedEntry(
                role=role,
                package_name=package_name,
                version_code=str(version_code),
                source=source,
                variants=[],
            )
        else:
            entry.ensure_variants()
        if llm_calls:
            entry.llm_calls = max(entry.llm_calls, llm_calls)
        if rediscovery_attempts is not None:
            entry.rediscovery_attempts = rediscovery_attempts

        fp = selector.fingerprint()
        for existing in entry.variants:
            if existing.selector.fingerprint() == fp:
                existing.nav_path = list(nav_path or existing.nav_path or [])
                existing.source = source
                if label:
                    existing.label = label
                existing.last_success_at = datetime.now().isoformat()
                existing.hits += 1
                entry.last_success_at = existing.last_success_at
                entry.selector = existing.selector
                entry.nav_path = list(existing.nav_path or [])
                entry.source = source
                self.put(entry)
                return entry, existing, None

        variant = LayoutVariant(
            selector=selector,
            nav_path=list(nav_path or []),
            source=source,
            label=label,
            hits=1,
            last_success_at=datetime.now().isoformat(),
        )
        entry.variants.append(variant)
        evicted: Optional[LayoutVariant] = None
        while len(entry.variants) > self.max_layout_variants:
            # Evict least-used (lowest hits, then highest misses, then oldest).
            # Never evict the variant we just added.
            candidates = [v for v in entry.variants if v.id != variant.id]
            if not candidates:
                break
            victim = min(
                candidates,
                key=lambda v: (v.hits, -v.misses, v.last_success_at or "", v.id),
            )
            entry.variants = [v for v in entry.variants if v.id != victim.id]
            evicted = victim
            log.info(
                "evicted layout variant role=%s id=%s hits=%s (cap=%s)",
                role,
                victim.id,
                victim.hits,
                self.max_layout_variants,
            )

        entry.selector = variant.selector
        entry.nav_path = list(variant.nav_path or [])
        entry.source = source
        entry.last_success_at = variant.last_success_at
        entry.discovered_at = variant.discovered_at
        self.put(entry)
        return entry, variant, evicted

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

    def invalidate_if_version_changed(
        self, package_name: str, old_version: str, new_version: str
    ) -> bool:
        if str(old_version) == str(new_version):
            return False
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
            e.ensure_variants()
            ordered = e.ordered_variants()
            best = ordered[0] if ordered else None
            role_rows.append(
                {
                    "role": role,
                    "selector": (best.selector if best else e.selector).to_dict(),
                    "discovered_at": e.discovered_at,
                    "llm_calls": e.llm_calls,
                    "rediscovery_attempts": e.rediscovery_attempts,
                    "source": best.source if best else e.source,
                    "last_success_at": e.last_success_at,
                    "last_failure_at": e.last_failure_at,
                    "version_code": e.version_code,
                    "nav_path": list((best.nav_path if best else e.nav_path) or []),
                    "variant_count": len(e.variants),
                    "max_layout_variants": self.max_layout_variants,
                    "variants": [v.to_dict() for v in ordered],
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
            max_layout_variants=self.max_layout_variants,
        )

    def list_packages(self) -> List[CacheStatus]:
        seen = set()
        out = []

        def _add(pkg: str, ver: str) -> None:
            key = (pkg, str(ver))
            if key in seen or not pkg:
                return
            seen.add(key)
            out.append(self.status(pkg, str(ver)))

        # Dynamo index is authoritative on AWS (survives cold starts / new /tmp)
        for pkg, ver in self._list_remote_packages():
            _add(pkg, ver)

        try:
            for path in self.persist_dir.glob("*.json"):
                try:
                    raw = json.loads(path.read_text())
                    pkg = raw.get("package_name")
                    ver = raw.get("version_code")
                    if pkg is None:
                        continue
                    _add(str(pkg), str(ver))
                except Exception:
                    continue
        except OSError:
            pass

        for _k, roles in self._mem.items():
            if not roles:
                continue
            e = next(iter(roles.values()))
            _add(e.package_name, e.version_code)
        return out

    def _payload(self, package_name: str, version_code: str) -> Dict[str, Any]:
        k = self._key(package_name, version_code)
        roles = self._mem.get(k) or {}
        return {
            "package_name": package_name,
            "version_code": str(version_code),
            "updated_at": int(time.time()),
            "total_llm_calls": self._llm_totals.get(k, 0),
            "max_layout_variants": self.max_layout_variants,
            "roles": {r: e.to_dict() for r, e in roles.items()},
        }

    def _persist(self, package_name: str, version_code: str) -> None:
        """Write local cache (best-effort) then Dynamo (source of truth on AWS)."""
        self._persist_local(package_name, version_code)
        self._save_remote(package_name, version_code)

    def _persist_local(self, package_name: str, version_code: str) -> None:
        path = self._path(package_name, version_code)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(self._payload(package_name, version_code), indent=2)
            )
        except OSError as e:
            log.debug("selector local cache write skipped: %s", e)

    def _load_remote(
        self, package_name: str, version_code: str
    ) -> Dict[str, CachedEntry]:
        roles, _meta = self._load_remote_full(package_name, version_code)
        return roles

    def _load_remote_full(
        self, package_name: str, version_code: str
    ) -> Tuple[Dict[str, CachedEntry], Dict[str, Any]]:
        get_user_setting, _ = _storage_get()
        if get_user_setting is None:
            return {}, {}
        try:
            data = get_user_setting(
                self.user_id, f"selectors:{package_name}:{version_code}"
            )
            if not data:
                return {}, {}
            roles = {
                role: CachedEntry.from_dict(d)
                for role, d in (data.get("roles") or {}).items()
            }
            return roles, data
        except Exception:
            log.debug("selector DynamoDB load failed", exc_info=True)
            return {}, {}

    def _list_remote_packages(self) -> List[Tuple[str, str]]:
        get_user_setting, _ = _storage_get()
        if get_user_setting is None:
            return []
        try:
            idx = get_user_setting(self.user_id, self.INDEX_SETTING) or {}
            out: List[Tuple[str, str]] = []
            for row in idx.get("packages") or []:
                if not isinstance(row, dict):
                    continue
                pkg = row.get("package_name")
                ver = row.get("version_code")
                if pkg is None:
                    continue
                out.append((str(pkg), str(ver if ver is not None else "0")))
            return out
        except Exception:
            log.debug("selector index load failed", exc_info=True)
            return []

    def _update_remote_index(self, package_name: str, version_code: str) -> None:
        get_user_setting, save_user_setting = _storage_get()
        if get_user_setting is None or save_user_setting is None:
            return
        try:
            idx = get_user_setting(self.user_id, self.INDEX_SETTING) or {}
            packages = list(idx.get("packages") or [])
            key = (str(package_name), str(version_code))
            found = False
            for row in packages:
                if not isinstance(row, dict):
                    continue
                if (
                    str(row.get("package_name")) == key[0]
                    and str(row.get("version_code")) == key[1]
                ):
                    found = True
                    break
            if not found:
                packages.append({"package_name": key[0], "version_code": key[1]})
            save_user_setting(
                self.user_id,
                self.INDEX_SETTING,
                {"packages": packages, "updated_at": int(time.time())},
            )
        except Exception:
            log.debug("selector index update failed", exc_info=True)

    def _save_remote(self, package_name: str, version_code: str) -> None:
        _, save_user_setting = _storage_get()
        if save_user_setting is None:
            return
        try:
            save_user_setting(
                self.user_id,
                f"selectors:{package_name}:{version_code}",
                self._payload(package_name, version_code),
            )
            self._update_remote_index(package_name, version_code)
        except Exception:
            log.debug("selector DynamoDB sync skipped", exc_info=True)

    def record_llm_call(self, package_name: str, version_code: str) -> None:
        k = self._key(package_name, version_code)
        self._llm_totals[k] = self._llm_totals.get(k, 0) + 1
