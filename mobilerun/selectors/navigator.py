"""High-level selector resolution for dating/social navigation.

Order:
1. Try cached layout variants (success-rate order) — no LLM; replay nav_path
2. Heuristic phrase / generic fallback (no LLM)
3. Bounded scroll exploration (up/down/left/right) — no LLM; add variant
4. ONE LLM discovery → derive selector → verify → add variant (evict if over cap)
5. If rediscovery exceeds cap → Needs-you escalate (never spam LLM)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from mobilerun.selectors.cache import SelectorCache
from mobilerun.selectors.discover import (
    derive_selector_from_node,
    heuristic_bootstrap,
    llm_locate,
    verify_selector,
)
from mobilerun.selectors.explore import (
    NavStep,
    explore_for_selector,
    replay_nav_path,
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
    source: str = ""  # cache | heuristic | explore | llm
    needs_you: bool = False
    reason: str = ""
    selector: Optional[SelectorSpec] = None
    nav_path: List[Dict[str, Any]] = field(default_factory=list)
    variant_id: Optional[str] = None
    variants_tried: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
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
            "nav_path": list(self.nav_path or []),
            "variant_id": self.variant_id,
            "variants_tried": self.variants_tried,
        }


class SelectorNavigator:
    def __init__(
        self,
        cache: Optional[SelectorCache] = None,
        *,
        max_rediscovery: int = 3,
        max_scrolls_per_direction: int = 4,
        max_layout_variants: Optional[int] = None,
        push_needs_you: Optional[Callable[..., str]] = None,
    ):
        if cache is None:
            cache = SelectorCache(
                max_rediscovery=max_rediscovery,
                max_layout_variants=max_layout_variants,
            )
        elif max_layout_variants is not None:
            from mobilerun.selectors.models import clamp_max_variants

            cache.max_layout_variants = clamp_max_variants(max_layout_variants)
        self.cache = cache
        self.max_rediscovery = max_rediscovery
        self.max_scrolls_per_direction = max_scrolls_per_direction
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
        get_tree: Optional[Callable[[], Any]] = None,
        perform_scroll: Optional[Callable[[NavStep], None]] = None,
        perform_tap_tab: Optional[Callable[[str], None]] = None,
        explore: bool = True,
        candidate_spec: Optional[SelectorSpec] = None,
    ) -> ResolveResult:
        role = role.value if isinstance(role, ElementRole) else str(role)
        version_code = str(version_code or "0")
        get_tree = get_tree or (lambda: tree)

        entry = self.cache.get(package_name, version_code, role)
        variants_tried = 0

        # 1) Try all cached layout variants in success-rate order (no LLM)
        if entry and entry.variants:
            for variant in entry.ordered_variants():
                if variant.selector.is_empty():
                    continue
                variants_tried += 1
                cur_tree = tree
                if variant.nav_path and perform_scroll:
                    try:
                        steps = [NavStep.from_dict(s) for s in variant.nav_path]
                        replay_nav_path(
                            steps,
                            perform_scroll=perform_scroll,
                            perform_tap_tab=perform_tap_tab,
                        )
                        cur_tree = get_tree()
                    except Exception:
                        log.debug("nav_path replay failed", exc_info=True)
                match = find_by_selector(cur_tree, variant.selector)
                if match:
                    self.cache.mark_variant_success(
                        package_name, version_code, role, variant.id
                    )
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
                        selector=variant.selector,
                        nav_path=list(variant.nav_path or []),
                        variant_id=variant.id,
                        variants_tried=variants_tried,
                    )
                self.cache.mark_variant_miss(
                    package_name, version_code, role, variant.id
                )

            # All variants missed — try discovery next; only burn rediscovery
            # budget if discovery also fails (so explore/LLM still get a chance).
            log.info(
                "all layout variants missed role=%s pkg=%s ver=%s tried=%s attempts=%s",
                role,
                package_name,
                version_code,
                variants_tried,
                entry.rediscovery_attempts,
            )
            entry = self.cache.get(package_name, version_code, role) or entry
        else:
            entry = entry or CachedEntry(
                role=role,
                selector=SelectorSpec(),
                package_name=package_name,
                version_code=version_code,
            )

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
                variants_tried=variants_tried,
            )

        # 2) Heuristic bootstrap (still no LLM)
        heur = heuristic_bootstrap(role, tree, package_name)
        if heur:
            spec = derive_selector_from_node(heur.node)
            verified = verify_selector(tree, spec) or heur
            _, variant, _ = self.cache.add_variant(
                package_name=package_name,
                version_code=version_code,
                role=role,
                selector=spec,
                source="heuristic",
                llm_calls=0,
                rediscovery_attempts=entry.rediscovery_attempts,
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
                variant_id=variant.id,
                variants_tried=variants_tried,
            )

        # 3) Bounded scroll exploration (no LLM)
        hunt_spec = candidate_spec
        if hunt_spec is None or hunt_spec.is_empty():
            from mobilerun.selectors.models import DEFAULT_SELECTORS, GENERIC_FALLBACKS

            hunt_spec = (
                (DEFAULT_SELECTORS.get(f"{package_name}@{version_code}") or {}).get(
                    role
                )
                or (DEFAULT_SELECTORS.get(package_name) or {}).get(role)
                or GENERIC_FALLBACKS.get(role)
            )
        if (
            explore
            and hunt_spec
            and not hunt_spec.is_empty()
            and perform_scroll is not None
        ):
            explored = explore_for_selector(
                hunt_spec,
                get_tree=get_tree,
                perform_scroll=perform_scroll,
                perform_tap_tab=perform_tap_tab,
                max_scrolls_per_direction=self.max_scrolls_per_direction,
            )
            if explored.found and explored.match:
                spec = derive_selector_from_node(explored.match.node)
                nav = [s.to_dict() for s in explored.nav_path]
                _, variant, _ = self.cache.add_variant(
                    package_name=package_name,
                    version_code=version_code,
                    role=role,
                    selector=spec,
                    source="explore",
                    nav_path=nav,
                    llm_calls=0,
                    rediscovery_attempts=entry.rediscovery_attempts,
                )
                return ResolveResult(
                    found=True,
                    role=role,
                    package_name=package_name,
                    version_code=version_code,
                    match=explored.match,
                    used_llm=False,
                    llm_calls=0,
                    cache_hit=False,
                    source="explore",
                    selector=spec,
                    nav_path=nav,
                    variant_id=variant.id,
                    variants_tried=variants_tried,
                )

        # 4) ONE LLM discovery
        if not allow_llm or llm_callable is None:
            self.cache.mark_failure(package_name, version_code, role)
            return ResolveResult(
                found=False,
                role=role,
                package_name=package_name,
                version_code=version_code,
                reason="selector not found and LLM discovery disabled",
                source="miss",
                variants_tried=variants_tried,
            )

        self.cache.record_llm_call(package_name, version_code)
        tree = get_tree()
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
                    variants_tried=variants_tried,
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
                variants_tried=variants_tried,
            )

        verified = verify_selector(tree, spec)
        nav: List[Dict[str, Any]] = []
        if not verified and explore and perform_scroll is not None:
            explored = explore_for_selector(
                spec,
                get_tree=get_tree,
                perform_scroll=perform_scroll,
                perform_tap_tab=perform_tap_tab,
                max_scrolls_per_direction=self.max_scrolls_per_direction,
            )
            if explored.found and explored.match:
                verified = explored.match
                nav = [s.to_dict() for s in explored.nav_path]

        if not verified:
            self.cache.mark_failure(package_name, version_code, role)
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
                variants_tried=variants_tried,
            )

        _, variant, _ = self.cache.add_variant(
            package_name=package_name,
            version_code=version_code,
            role=role,
            selector=spec,
            source="llm",
            nav_path=nav,
            llm_calls=1,
            rediscovery_attempts=entry.rediscovery_attempts,
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
            nav_path=nav,
            variant_id=variant.id,
            variants_tried=variants_tried,
        )

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
