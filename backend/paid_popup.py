"""r50: one paid-popup detector + closer for every fixed planner.

Mac (24 Nov 11:01): "ability to skip or close any paid pop ups" — all apps.

A screen is a paid popup when it has NO text box (compose / comment sheets
and the Yubo Direct/Blast sheet are left to their planners) and either
  * a price / billing line (£9.99, $4.99, € 2,99, per week, /month,
    "Recurring billing", "Cancel anytime", "free trial", "auto-renew"), or
  * a paid word (premium, gold, platinum, plus, boost, super like, coins,
    credits, VIP, spotlight, rose, blast, upgrade, subscribe, trial, unlock,
    infinity…) AND a paid button (Continue, Subscribe, Upgrade, Buy…, Get…,
    Try…, Unlock…, Send a Super Like) on a small screen (≤ 6 buttons —
    full app pages with a premium banner have many more).
Close: "Send like anyway" (free) > Not now / No thanks / Maybe later /
Close / X / Skip / Cancel / Dismiss > Back. Never Continue, Buy, Upgrade,
Subscribe, Try, Get, Unlock, Allow.

Real popup trees covered by tests: Badoo Buy Credits, BLK Get Boost, BLK
Super Like, Taimi GOLD, Yubo Infinity, Hily paywall. Others are guesses.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

try:
    from dm_heuristics import _fp, _parse_compact_nodes
except ImportError:  # pragma: no cover
    from backend.dm_heuristics import _fp, _parse_compact_nodes  # type: ignore

_PRICE_RE = re.compile(
    r"[£$€]\s?\d|\d[\d.,]*\s?[£€]|\bper (?:week|month|year)\b|/\s?(?:week|wk|month|mo|year)\b"
    r"|recurring billing|cancel anytime|free trial|auto-?renew|billed (?:weekly|monthly)",
    re.I,
)
_PAID_WORDS = re.compile(
    r"premium|\bgold\b|platinum|\bplus\b|boost|super ?like|superswipe|super swipe|coins?\b"
    r"|credits?\b|\bvip\b|spotlight|\broses?\b|\bblast\b|upgrade|subscri|\btrial\b|unlock"
    r"|infinity|yubucks|hingex|\bcrush\b",
    re.I,
)
_PAID_CTA = re.compile(
    r"^(?:continue|subscribe|upgrade|buy\b.*|get\b.*|try\b.*|unlock\b.*|start (?:free )?trial"
    r"|send (?:a )?super ?like|purchase|pay\b.*|see plans|view plans)$",
    re.I,
)
_CLOSE_ORDER = (
    ("send like anyway",),
    ("not now", "no thanks", "no, thanks", "no thanks!", "maybe later", "later",
     "remind me later", "not interested", "keep swiping", "skip"),
    ("close", "x", "✕", "×", "cancel", "dismiss", "got it", "got it!"),
)
_NEVER = re.compile(r"continue|\bbuy\b|upgrade|subscribe|\btry\b|\bget\b|unlock|allow|purchase"
                    r"|super ?like\b(?! instead)|boost|\bpay\b", re.I)


def _label(n: Dict[str, Any]) -> str:
    return str(n.get("text") or n.get("label") or n.get("desc") or "").strip()


def is_paid_popup(tree: str) -> bool:
    nodes = _parse_compact_nodes(tree or "")
    if not nodes or any(n.get("editable") for n in nodes):
        return False
    labels = [_label(n) for n in nodes]
    blob = " ".join(labels)
    if _PRICE_RE.search(blob):
        return True
    if not _PAID_WORDS.search(blob):
        return False
    clickable = [n for n in nodes if n.get("clickable")]
    cta = any(_PAID_CTA.match(_label(n).lower().strip(" .!")) for n in clickable)
    return cta and len(clickable) <= 6


def paid_close_target(tree: str) -> Optional[Tuple[int, int, str]]:
    nodes = [n for n in _parse_compact_nodes(tree or "") if n.get("x") is not None]
    for group in _CLOSE_ORDER:
        for n in nodes:
            lab = _label(n).lower().strip(" .")
            nid = str(n.get("id") or "").lower()
            if lab in group or (group[0] == "close" and (
                    "close" in nid or nid.endswith("dismiss") or "button2" in nid)):
                if _NEVER.search(lab) and lab != "send like anyway":
                    continue
                return (int(n["x"]), int(n["y"]), lab or nid)
    return None


def paid_popup_action(tree: str, planner: str, state: Optional[Dict[str, Any]] = None
                      ) -> Optional[Dict[str, Any]]:
    """One close step for a paid popup, or None. Drops any like awaiting
    verification (the popup came up instead of the next card)."""
    if not is_paid_popup(tree):
        if isinstance(state, dict):
            state.pop("paid_popup_n", None)
        return None
    st = state if isinstance(state, dict) else {}
    for k in ("hily_run", "tinder_run", "fixed_like_run"):
        r = st.get(k)
        if isinstance(r, dict):
            for a in ("awaiting_like", "awaiting"):
                if r.get(a):
                    r[a] = False
                    r["unverified" if k != "hily_run" else "unverified_likes"] = int(
                        r.get("unverified" if k != "hily_run" else "unverified_likes") or 0) + 1
    n = int(st.get("paid_popup_n") or 0) + 1
    st["paid_popup_n"] = n
    st["paid_popups_closed"] = int(st.get("paid_popups_closed") or 0) + 1
    base = {"planner": planner, "llm_provider": None, "_no_llm_handoff": True}
    if n > 6:
        return _fp({**base, "action": "fail",
                    "reason": f"Paid popup will not close after 6 tries — stopped, nothing bought ({planner})"},
                   "paid_popup_stuck")
    c = paid_close_target(tree) if n <= 3 else None
    if c:
        return _fp({**base, "action": "tap", "x": c[0], "y": c[1],
                    "reason": f"Paid popup — '{c[2]}' (never Continue/Buy/Upgrade) ({planner})"},
                   "paid_popup_close")
    return _fp({**base, "action": "press_button", "button": "back",
                "reason": f"Paid popup — Back (never Continue/Buy/Upgrade) ({planner})"},
               "paid_popup_back")
