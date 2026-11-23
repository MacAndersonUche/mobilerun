"""Dating deck helpers: free LIKE, wait-for-next-card, paywall dismiss, messaging.

Hard rules:
- Free like / heart / thumbs-up / swipe-right only — never Super Like, Crush,
  Rose, Boost, Gold, credits, Google Play billing, Samsung Pay/Wallet.
- After like/pass: wait until card fingerprint changes or end-of-deck / timeout.
- Messages: bank text or exact instruction quotes only (callers enforce).
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("mobilerun.dating_deck")

CARD_WAIT_MAX = 8  # ~ poll steps before giving up on same card
CARD_WAIT_SECONDS = 0.9

_PAYWALL_MARKERS: Tuple[str, ...] = (
    "recurring billing",
    "google play",
    "play store",
    "complete your purchase",
    "subscribe now",
    "start free trial",
    "trial then",
    "cancel anytime",
    "get premium",
    "go premium",
    "upgrade to premium",
    "get gold",
    "bumble premium",
    "bumble boost",
    "get boost",
    "boost now",
    "buy credits",
    "buy roses",
    "send a rose",
    "send rose",
    # Note: bare "super like" / "superswipe" labels are paid CTAs on a normal
    # deck — not enough alone to call the whole screen a paywall sheet.
    "send a super like",
    "send superswipe",
    "major crush",
    "get crush",
    "crush now",
    "hinge+",
    "hingex",
    "preferred members",
    "dating intent",
    "yubucks",
    "blast",
    "tagged premium",
    "continue to pay",
    "add payment",
    "allow payment",
    "payment method",
    "samsung pay",
    "samsung wallet",
    "spay",
    # r28: Yubo Reactions / Elite Pack / See who added you
    "elite pack",
    "see who added you",
    "see who liked you",
    "who added you",
    "unlock reactions",
    "reactions are blurred",
)

_PAID_CTA_NEVER: Tuple[str, ...] = (
    "get boost",
    "boost now",
    "buy",
    "purchase",
    "subscribe",
    "upgrade",
    "continue",  # often GOLD Continue — only if paywall context
    "get gold",
    "get premium",
    "send a rose",
    "send rose",
    "super like",
    "superswipe",
    "crush",
    "allow payment",
    "add card",
    "checkout",
)

_SAFE_PAYWALL_DISMISS: Tuple[str, ...] = (
    "not now",
    "no thanks",
    "maybe later",
    "later",
    "skip",
    "close",
    "dismiss",
    "cancel",
    "no",
    "got it",
    "got it!",
    "x",
)

_END_OF_DECK: Tuple[str, ...] = (
    "no more profiles",
    "no more people",
    "you've seen everyone",
    "youve seen everyone",
    "out of likes",
    "out of people",
    "oh no! you reached the end",
    "reached the end of the deck",
    "there's no one new",
    "theres no one new",
    "check back later",
    "come back later",
    "no one around",
    "end of the line",
)

_FREE_LIKE_LABELS: Tuple[str, ...] = (
    "like",
    "heart",
    "thumbs up",
    "thumbsup",
    "yes",
    "voteyes",
    "send like",
    "send like anyway",
)


def _tree_blob(tree: str) -> str:
    return (tree or "").lower()


def deck_fingerprint(tree: str, app: str = "") -> str:
    """Stable-ish hash of the current card (name + mid-screen text)."""
    try:
        from bulk_bench_heuristics import deck_card_name
    except ImportError:
        from backend.bulk_bench_heuristics import deck_card_name  # type: ignore

    name = deck_card_name(app, tree) if app else None
    # Mid-screen text sample
    texts: List[str] = []
    for m in re.finditer(r'\bt="([^"]{2,40})"', tree or ""):
        t = m.group(1).strip().lower()
        if t and t not in ("like", "pass", "chat", "chats", "messages"):
            texts.append(t)
        if len(texts) >= 8:
            break
    raw = f"{app}|{name or ''}|{'|'.join(texts[:6])}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def is_end_of_deck(tree: str) -> bool:
    blob = _tree_blob(tree)
    return any(m in blob for m in _END_OF_DECK)


def _visible_label_blob(tree: str) -> str:
    """Join t=/d=/h=/text=/content-desc labels — ignore resource-id noise."""
    parts: List[str] = []
    for m in re.finditer(r'\b(?:t|d|h|text|content-desc)="([^"]*)"', tree or "", re.I):
        t = (m.group(1) or "").strip().lower()
        if t:
            parts.append(t)
    return " | ".join(parts)


def is_paywall_or_billing(tree: str, package: str = "") -> bool:
    """True for subscription / credits / Play billing / Spay / Wallet sheets."""
    pkg = (package or "").lower()
    if any(
        x in pkg
        for x in (
            "spay",
            "samsung.android.spay",
            "samsungpay",
            "vending",
            "android.gms",
            "billing",
            "securefolder",
        )
    ):
        return True
    labels = _visible_label_blob(tree)
    if any(m in labels for m in _PAYWALL_MARKERS):
        return True
    # Play Billing chrome in package attrs
    blob = _tree_blob(tree)
    if "com.android.vending" in blob or "google play" in labels:
        return True
    return False


def _node_hits(tree: str) -> List[Tuple[int, int, str]]:
    out: List[Tuple[int, int, str]] = []
    for m in re.finditer(r"<n\b([^>]*)>", tree or "", re.I):
        attrs = m.group(1)
        xy = re.search(r'\bxy="(\d+),(\d+)"', attrs)
        if not xy:
            continue
        x, y = int(xy.group(1)), int(xy.group(2))
        label = ""
        for key in ("t", "d", "h"):
            lm = re.search(rf'\b{key}="([^"]*)"', attrs, re.I)
            if lm and lm.group(1).strip():
                label = lm.group(1).strip()
                break
        out.append((x, y, label))
    return out


def _is_paid_cta(label: str) -> bool:
    low = (label or "").lower().strip()
    if not low:
        return False
    # Exact "Like" is free — "Super Like" is paid
    if low == "like" or low == "send like" or low == "send like anyway":
        return False
    return any(p in low for p in _PAID_CTA_NEVER)


def is_yubo_reactions_or_elite_paywall(tree: str) -> bool:
    """True for Yubo blurred Reactions list / Elite Pack / See who added you."""
    blob = (tree or "").lower()
    if not blob:
        return False
    markers = (
        "elite pack",
        "see who added you",
        "see who liked you",
        "who added you",
        "recurring billing",
        "unlock reactions",
        "reactions are blurred",
    )
    if any(m in blob for m in markers):
        return True
    if "reactions" in blob and (
        "added you" in blob or "elite" in blob or "subscribe" in blob
    ):
        return True
    return False


def yubo_paywall_back_action(
    tree: str, *, planner: str = "yubo_paywall"
) -> Optional[Dict[str, Any]]:
    """Back out of Yubo Reactions / Elite Pack paywall pages entirely."""
    if not is_yubo_reactions_or_elite_paywall(tree):
        return None
    return {
        "action": "press_button",
        "button": "back",
        "reason": f"Yubo Reactions/Elite Pack paywall — Back out ({planner})",
        "planner": planner,
        "llm_provider": None,
        "_paywall_dismiss": True,
        "_yubo_reactions_block": True,
    }


def dismiss_paywall_action(
    tree: str,
    *,
    package: str = "",
    planner: str = "dating_deck",
) -> Optional[Dict[str, Any]]:
    """Close paywall / billing / Spay — safe dismiss or Back. Never paid CTA."""
    yubo = yubo_paywall_back_action(tree, planner=planner)
    if yubo:
        return yubo
    if not is_paywall_or_billing(tree, package):
        # Per-app Taimi GOLD helper
        try:
            from dm_heuristics import taimi_dismiss_paywall, taimi_is_paywall
        except ImportError:
            from backend.dm_heuristics import (  # type: ignore
                taimi_dismiss_paywall,
                taimi_is_paywall,
            )

        if taimi_is_paywall(tree):
            return taimi_dismiss_paywall(tree, planner=planner)
        return None

    for x, y, lab in _node_hits(tree):
        low = lab.lower().strip()
        # Exact / short-button match only — never substring of billing copy
        # (e.g. "Cancel anytime" must NOT match safe "cancel").
        exact = low in _SAFE_PAYWALL_DISMISS
        short_btn = len(low) <= 16 and any(
            low == s or low.startswith(s + " ")
            for s in _SAFE_PAYWALL_DISMISS
            if len(s) > 1
        )
        if exact or short_btn:
            if _is_paid_cta(lab):
                continue
            return {
                "action": "tap",
                "x": x,
                "y": y,
                "label": lab,
                "reason": f"Dismiss paywall/billing '{lab}' ({planner})",
                "planner": planner,
                "llm_provider": None,
                "_paywall_dismiss": True,
            }
    # Spay / Wallet / Play → Back
    return {
        "action": "press_button",
        "button": "back",
        "reason": f"Dismiss paywall/billing/Spay → Back ({planner})",
        "planner": planner,
        "llm_provider": None,
        "_paywall_dismiss": True,
    }


def find_free_like_target(
    tree: str,
    app: str = "",
) -> Optional[Tuple[int, int, str]]:
    """Locate free Like / heart — never Super Like / Crush / Rose."""
    app_l = (app or "").lower()
    # Prefer resource-ids from profiles
    try:
        from dm_heuristics import DM_APP_PROFILES, _tree_id_center
    except ImportError:
        from backend.dm_heuristics import DM_APP_PROFILES, _tree_id_center  # type: ignore

    prof = DM_APP_PROFILES.get(app_l) or {}
    like_ids = tuple(prof.get("like_ids") or ())
    # Explicit free like ids (exclude crush / super)
    free_ids = like_ids + (
        "ActionButton_LIKE",
        "id/ActionButton_LIKE",
        "likeBtn",
        "id/likeBtn",
        "gamepad_like",
        "id/gamepad_like",
        "encounters_profile_voting_buttonVoteYes",
        "btn_like",
        "id/btn_like",
    )
    # Filter out paid-looking ids
    free_ids = tuple(
        i
        for i in free_ids
        if i
        and "crush" not in i.lower()
        and "super" not in i.lower()
        and "rose" not in i.lower()
        and "boost" not in i.lower()
    )
    if free_ids:
        c = _tree_id_center(tree, *free_ids)
        if c:
            return (int(c[0]), int(c[1]), "like_id")

    # Exact label match — "Like" not "Super Like"
    for x, y, lab in _node_hits(tree):
        low = lab.lower().strip()
        if low in _FREE_LIKE_LABELS:
            if _is_paid_cta(lab):
                continue
            # Prefer action row (lower half) over header
            if y < 400:
                continue
            return (x, y, lab)
    return None


def plan_free_like(
    app: str,
    tree: str,
    *,
    planner: str = "dating_deck",
    dry_run: bool = False,
) -> Optional[Dict[str, Any]]:
    """Free like action for any dating app — never paid variants."""
    app_l = (app or "").lower()
    if dry_run:
        return {
            "action": "done",
            "reason": f"[DRY RUN] would free-like on {app_l or '?'} — no tap ({planner})",
            "planner": planner,
            "llm_provider": None,
            "dry_run": True,
            "dry_run_verified": True,
        }

    # Prefer an explicit free Like / heart tap when present (never Super/Crush)
    hit = find_free_like_target(tree, app_l)
    if hit:
        x, y, lab = hit
        return {
            "action": "tap",
            "x": x,
            "y": y,
            "label": lab if lab != "like_id" else "Like",
            "reason": f"Free like '{lab}' ({planner})",
            "planner": planner,
            "llm_provider": None,
            "_free_like": True,
        }

    # Per-app mapped gestures (swipe-right / gamepad) when no labeled button
    try:
        from bulk_bench_heuristics import _real_like_action
    except ImportError:
        from backend.bulk_bench_heuristics import _real_like_action  # type: ignore

    act = _real_like_action(app_l, tree=tree, planner=planner)
    if act:
        blob = f"{act.get('reason')} {act.get('label')}".lower()
        if any(
            p in blob
            for p in ("super like", "crush", "rose", "boost", "gold", "premium")
        ):
            logger.warning("refusing paid-looking like: %s", act.get("reason"))
        else:
            act = dict(act)
            act["_free_like"] = True
            act["planner"] = planner
            return act

    # Swipe-right fallback only for mapped real decks that already use swipe
    # likes — never invent a swipe for apps that must fail-closed (e.g. Tinder
    # fake-chats without a Like control).
    if app_l in ("bumble", "yubo", "hinge"):
        return {
            "action": "swipe",
            "x1": 200,
            "y1": 1400,
            "x2": 900,
            "y2": 1400,
            "reason": f"Free like swipe-right ({planner})",
            "planner": planner,
            "llm_provider": None,
            "_free_like": True,
        }
    return None


def plan_wait_for_next_card(
    state: Dict[str, Any],
    *,
    app: str,
    tree: str,
    planner: str = "dating_deck",
) -> Optional[Dict[str, Any]]:
    """After like/pass: wait until card changes or end-of-deck / timeout.

    Uses ``state['bulk_swipe']`` (or ``state['deck_wait']``) fields:
    ``awaiting_verify``, ``last_fp`` / ``last_name``, ``card_wait_n``.
    """
    bulk = state.setdefault("bulk_swipe", {}) if isinstance(state, dict) else {}
    if not isinstance(bulk, dict):
        return None
    if not bulk.get("awaiting_verify"):
        return None

    if is_end_of_deck(tree):
        bulk["awaiting_verify"] = False
        bulk["card_wait_n"] = 0
        bulk["end_of_deck"] = True
        state["bulk_swipe"] = bulk
        return {
            "action": "done",
            "reason": f"End of deck after like/pass ({planner})",
            "planner": planner,
            "llm_provider": None,
            "stopped_reason": "end_of_deck",
        }

    # Paywall after like → dismiss first
    pay = dismiss_paywall_action(tree, planner=planner)
    if pay:
        return pay

    try:
        from bulk_bench_heuristics import deck_card_name
    except ImportError:
        from backend.bulk_bench_heuristics import deck_card_name  # type: ignore

    name_now = deck_card_name(app, tree)
    fp_now = deck_fingerprint(tree, app)
    last_name = bulk.get("last_name")
    last_fp = bulk.get("last_fp")

    changed = False
    if name_now and last_name and name_now != last_name:
        changed = True
    elif fp_now and last_fp and fp_now != last_fp:
        changed = True
    elif name_now and not last_name:
        # First readable card after action — treat as settled once
        changed = int(bulk.get("card_wait_n") or 0) >= 1

    if changed:
        done = int(bulk.get("done") or 0) + 1
        bulk["done"] = done
        bulk["last_name"] = name_now
        bulk["last_fp"] = fp_now
        bulk["awaiting_verify"] = False
        bulk["card_wait_n"] = 0
        state["bulk_swipe"] = bulk
        logger.info(
            "card changed → count like done=%s name=%s", done, name_now or fp_now
        )
        return None  # caller continues with next like

    waits = int(bulk.get("card_wait_n") or 0) + 1
    bulk["card_wait_n"] = waits
    state["bulk_swipe"] = bulk
    if waits <= CARD_WAIT_MAX:
        return {
            "action": "wait",
            "seconds": CARD_WAIT_SECONDS,
            "reason": (
                f"Wait for next profile ({waits}/{CARD_WAIT_MAX}) "
                f"after like/pass ({planner})"
            ),
            "planner": planner,
            "llm_provider": None,
            "_card_wait": True,
        }

    # Timeout — don't count; clear and let stuck recovery escalate
    bulk["awaiting_verify"] = False
    bulk["card_wait_n"] = 0
    state["bulk_swipe"] = bulk
    logger.warning("card wait timeout app=%s last=%s now=%s", app, last_name, name_now)
    return {
        "action": "wait",
        "seconds": 0.4,
        "reason": f"Card did not change after like — timeout ({planner})",
        "planner": planner,
        "llm_provider": None,
        "_card_wait_timeout": True,
        "needs_vision": True,
        "_force_vision": True,
    }


def mark_like_issued(
    state: Dict[str, Any],
    *,
    app: str,
    tree: str,
) -> None:
    """Call right after issuing a like/pass — starts card-wait polling."""
    try:
        from bulk_bench_heuristics import deck_card_name
    except ImportError:
        from backend.bulk_bench_heuristics import deck_card_name  # type: ignore

    bulk = state.setdefault("bulk_swipe", {})
    if not isinstance(bulk, dict):
        return
    bulk["last_name"] = deck_card_name(app, tree)
    bulk["last_fp"] = deck_fingerprint(tree, app)
    bulk["awaiting_verify"] = True
    bulk["card_wait_n"] = 0
    state["bulk_swipe"] = bulk


def skip_new_contact_on_paywall(
    state: Dict[str, Any],
    *,
    tree: str,
    package: str = "",
    planner: str = "dating_deck",
    name: str = "",
) -> Optional[Dict[str, Any]]:
    """If paywall/upsell while messaging a new person: dismiss, skip, continue.

    Clears ``bulk_message_new.current`` and records the name in ``skipped`` so
    the planner tries the next person. Never taps paid CTAs.
    """
    pay = dismiss_paywall_action(tree, package=package, planner=planner)
    if not pay:
        return None
    bulk = state.setdefault("bulk_message_new", {})
    if not isinstance(bulk, dict):
        bulk = {}
        state["bulk_message_new"] = bulk
    skipped = list(bulk.get("skipped") or [])
    cur = (name or str(bulk.get("current") or "")).strip()
    if cur and cur.lower() not in {str(x).lower() for x in skipped}:
        skipped.append(cur)
    bulk["skipped"] = skipped
    bulk["current"] = None
    bulk["typed"] = False
    bulk["awaiting_send"] = False
    bulk["_paywall_skips"] = int(bulk.get("_paywall_skips") or 0) + 1
    state["bulk_message_new"] = bulk
    out = dict(pay)
    out["_new_contact_paywall_skip"] = True
    out["reason"] = (
        f"Paywall on new contact"
        f"{f' ({cur})' if cur else ''} — dismiss + skip to next ({planner})"
    )
    return out


def find_free_compose_center(tree: str) -> Optional[Tuple[int, int]]:
    """Locate a free message composer (EditText / Message hint) — not Crush/Rose."""
    for m in re.finditer(r"<n\b([^>]*)>", tree or "", re.I):
        attrs = m.group(1)
        editable = 'e="1"' in attrs or "editable" in attrs.lower()
        hint = ""
        for key in ("h", "t", "d"):
            hm = re.search(rf'\b{key}="([^"]*)"', attrs, re.I)
            if hm and hm.group(1).strip():
                hint = hm.group(1).strip().lower()
                break
        xy = re.search(r'\bxy="(\d+),(\d+)"', attrs)
        if not xy:
            continue
        x, y = int(xy.group(1)), int(xy.group(2))
        if y < 1200:
            continue
        if any(bad in hint for bad in ("search", "crush", "rose", "boost", "super")):
            continue
        if editable or hint in (
            "message",
            "type a message",
            "say something",
            "write a message",
            "aa",
            "hey",
        ):
            return (x, y)
    return None
