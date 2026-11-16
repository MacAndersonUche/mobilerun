"""High-level selector resolution for dating/social navigation.

Order:
1. Cached selector for package + version_code (no LLM)
2. Heuristic phrase / generic fallback (no LLM)
3. ONE LLM discovery → derive selector → verify → persist
4. If rediscovery exceeds cap → Needs-you escalate (never spam LLM)
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, Optional

from mobilerun.selectors.cache import SelectorCache
from mobilerun.selectors.discover import (
    derive_selector_from_node,
    heuristic_bootstrap,
    llm_locate,
    verify_selector,
)
from mobilerun.selectors.match import find_by_selector
from mobilerun.selectors.models import (
    CachedEntry,
    ElementRole,
    SelectorMatch,
    SelectorSpec,
)

log = logging.getLogger("mobilerun.selectors.navigator")


@dataclass
class ResolveResult:
    found: bool
    role: str
    package_name: str
    version_code: str
    match: Optional[SelectorMatch] = None
    used_llm: bool = False
    llm_calls: int = 0
    cache_hit: bool = False
    source: str = ""  # cache | heuristic | llm
    needs_you: bool = False
    reason: str = ""
    selector: Optional[SelectorSpec] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "found": self.found,
            "role": self.role,
            "package_name": self.package_name,
            "version_code": self.version_code,
            "used_llm": self.used_llm,
            "llm_calls": self.llm_calls,
            "cache_hit": self.cache_hit,
            "source": self.source,
            "needs_you": self.needs_you,
            "reason": self.reason,
            "selector": self.selector.to_dict() if self.selector else None,
            "center": self.match.center if self.match else None,
        }
        return d


class SelectorNavigator:
    def __init__(
        self,
        cache: Optional[SelectorCache] = None,
        *,
        max_rediscovery: int = 3,
        push_needs_you: Optional[Callable[..., str]] = None,
    ):
        self.cache = cache or SelectorCache(max_rediscovery=max_rediscovery)
        self.max_rediscovery = max_rediscovery
        self.push_needs_you = push_needs_you

    def resolve(
        self,
        *,
        role: str,
        package_name: str,
        version_code: str,
        tree: Any,
        screenshot_b64: Optional[str] = None,
        llm_callable: Optional[Callable[..., Any]] = None,
        allow_llm: bool = True,
    ) -> ResolveResult:
        role = role.value if isinstance(role, ElementRole) else str(role)
        version_code = str(version_code or "0")

        # 1) Cache hit
        entry = self.cache.get(package_name, version_code, role)
        if entry and not entry.selector.is_empty():
            match = find_by_selector(tree, entry.selector)
            if match:
                self.cache.mark_success(package_name, version_code, role)
                return ResolveResult(
                    found=True,
                    role=role,
                    package_name=package_name,
                    version_code=version_code,
                    match=match,
                    used_llm=False,
                    llm_calls=0,
                    cache_hit=True,
                    source="cache",
                    selector=entry.selector,
                )
            # Cached selector failed — count toward rediscovery
            entry = self.cache.mark_failure(package_name, version_code, role)
            log.info(
                "cached selector miss role=%s pkg=%s ver=%s attempts=%s",
                role,
                package_name,
                version_code,
                entry.rediscovery_attempts,
            )
        else:
            entry = entry or CachedEntry(
                role=role,
                selector=SelectorSpec(),
                package_name=package_name,
                version_code=version_code,
            )

        # Cap — escalate instead of more LLM
        if entry.rediscovery_attempts >= self.max_rediscovery:
            reason = (
                f"Selector rediscovery failed {entry.rediscovery_attempts} times "
                f"for {role} on {package_name} v{version_code}"
            )
            self._escalate(package_name, role, reason)
            return ResolveResult(
                found=False,
                role=role,
                package_name=package_name,
                version_code=version_code,
                needs_you=True,
                reason=reason,
                source="escalated",
            )

        # 2) Heuristic bootstrap (still no LLM)
        heur = heuristic_bootstrap(role, tree, package_name)
        if heur:
            spec = derive_selector_from_node(heur.node)
            verified = verify_selector(tree, spec) or heur
            self._persist(
                package_name,
                version_code,
                role,
                spec,
                source="heuristic",
                llm_calls=0,
                attempts=entry.rediscovery_attempts,
            )
            return ResolveResult(
                found=True,
                role=role,
                package_name=package_name,
                version_code=version_code,
                match=verified,
                used_llm=False,
                llm_calls=0,
                cache_hit=False,
                source="heuristic",
                selector=spec,
            )

        # 3) ONE LLM discovery
        if not allow_llm or llm_callable is None:
            return ResolveResult(
                found=False,
                role=role,
                package_name=package_name,
                version_code=version_code,
                reason="selector not found and LLM discovery disabled",
                source="miss",
            )

        self.cache.record_llm_call(package_name, version_code)
        spec = llm_locate(
            role=role,
            tree=tree,
            screenshot_b64=screenshot_b64,
            llm_callable=llm_callable,
        )
        if not spec:
            failed = self.cache.mark_failure(package_name, version_code, role)
            if failed.rediscovery_attempts >= self.max_rediscovery:
                reason = f"LLM could not locate {role} after retries"
                self._escalate(package_name, role, reason)
                return ResolveResult(
                    found=False,
                    role=role,
                    package_name=package_name,
                    version_code=version_code,
                    used_llm=True,
                    llm_calls=1,
                    needs_you=True,
                    reason=reason,
                    source="llm",
                )
            return ResolveResult(
                found=False,
                role=role,
                package_name=package_name,
                version_code=version_code,
                used_llm=True,
                llm_calls=1,
                reason="LLM discovery returned no selector",
                source="llm",
            )

        verified = verify_selector(tree, spec)
        if not verified:
            failed = self.cache.mark_failure(package_name, version_code, role)
            return ResolveResult(
                found=False,
                role=role,
                package_name=package_name,
                version_code=version_code,
                used_llm=True,
                llm_calls=1,
                reason="LLM selector failed verification",
                source="llm",
                selector=spec,
            )

        self._persist(
            package_name,
            version_code,
            role,
            spec,
            source="llm",
            llm_calls=1,
            attempts=entry.rediscovery_attempts,
        )
        return ResolveResult(
            found=True,
            role=role,
            package_name=package_name,
            version_code=version_code,
            match=verified,
            used_llm=True,
            llm_calls=1,
            cache_hit=False,
            source="llm",
            selector=spec,
        )

    def _persist(
        self,
        package_name: str,
        version_code: str,
        role: str,
        spec: SelectorSpec,
        *,
        source: str,
        llm_calls: int,
        attempts: int,
    ) -> None:
        entry = CachedEntry(
            role=role,
            selector=spec,
            package_name=package_name,
            version_code=version_code,
            discovered_at=datetime.now().isoformat(),
            llm_calls=llm_calls,
            rediscovery_attempts=attempts,
            last_success_at=datetime.now().isoformat(),
            source=source,
        )
        self.cache.put(entry)

    def _escalate(self, package_name: str, role: str, reason: str) -> None:
        if not self.push_needs_you:
            return
        try:
            self.push_needs_you(
                kind="selector_discovery",
                app=package_name,
                title=f"Needs you · {package_name}",
                body=reason
                + ". Selector rediscovery capped — handle the screen, then resume.",
                category="selector_cache",
                meta={"role": role},
            )
        except TypeError:
            try:
                self.push_needs_you(reason)  # type: ignore[misc]
            except Exception:
                log.exception("needs-you escalate failed")
        except Exception:
            log.exception("needs-you escalate failed")
