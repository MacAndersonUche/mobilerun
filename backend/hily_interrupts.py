"""r49: Hily auto-like interrupts — close anything that is not the Finder
card, and answer a match popup with a message-bank line, then carry on.

Mac (24 Nov 10:46): "if anything else appears on the screen like
notifications or a match close it go back to the finder card and continue
or send the message if its for a match then continue".

Detection is from what IS in the screen tree (the Finder card itself often
is not — r47). Real dumps exist for: first-like "Got it", notification
"Maybe later", Filter tip, Message-sent sheet, thread composer ids
(threadInputFieldText / threadSend) — 19 Nov map.
GUESSES (no real Hily match dump yet): the match popup wording ("It's a
match", "You matched", "matched with", "New match", "You both liked",
"Say hi"), its close labels, and the system permission dialog ids.
Never: Allow, Buy, Upgrade, Subscribe, Get premium, Crush, Boost, paid
message; never "Continue" on a sheet that mentions a price/premium.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

try:
    from dm_heuristics import _fp, _parse_compact_nodes, _tree_id_center
except ImportError:  # pragma: no cover
    from backend.dm_heuristics import (  # type: ignore
        _fp,
        _parse_compact_nodes,
        _tree_id_center,
    )

PKG = "com.hily.app"
_MATCH_NEEDLES = (
    "it's a match",
    "it’s a match",
    "its a match",
    "you matched",
    "matched with",
    "new match",
    "you both liked",
    "mutual like",
    "it's mutual",
    "it’s mutual",
)
_PAID_NEEDLES = (
    "premium", "subscribe", "upgrade", "buy ", "purchase", "£", "$", "€",
    "per week", "per month", "/week", "/month", "major crush", "boost",
    "free trial", "unlock",
    # r49 Tinder
    "super like", "gold", "platinum", "tinder plus", "tinder+", "see who likes you",
)
_SAFE_CLOSE = (
    "not now", "maybe later", "no thanks", "no, thanks", "later", "skip",
    "got it", "got it!", "keep swiping", "keep browsing", "continue swiping",
    "back to finder", "close", "keep playing", "maybe later", "no thanks!", "dismiss", "cancel", "not interested",
    "don't allow", "don’t allow", "deny", "never", "remind me later", "ok",
)
_NEVER = (
    "allow", "buy", "upgrade", "subscribe", "get premium", "try premium",
    "crush", "boost", "purchase", "unlock", "send a crush", "continue",
    "rate", "rate us", "rate now", "5 stars",
    # r49 Tinder: never Super Like / Boost / Gold / Platinum / Plus
    "super like", "get gold", "get platinum", "get tinder", "try gold", "see who likes you",
    "upgrade", "get super likes", "rewind",
)
_RE_SEND = re.compile(r"\bsend\b", re.I)


def _label(n: Dict[str, Any]) -> str:
    return str(n.get("text") or n.get("label") or n.get("desc") or "").strip()


def _blob(tree: str) -> str:
    return " ".join(_label(n) for n in _parse_compact_nodes(tree)).lower()


_KNOWN_SCREENS = ("finderFiltersButton", "bottomNavTab_", "threadInputFieldText",
                  "threadToolBar", "dialogMessageItem", "chat_request", "center_name",
                  "ActionButton_LIKE")


def finder_chrome(tree: str) -> bool:
    """Finder header, any Hily bottom tab, or a known Hily page (thread, Likes
    sent) is on screen — not a popup; the main planner handles those."""
    t = tree or ""
    return any(k in t for k in _KNOWN_SCREENS)


def is_match_popup(tree: str) -> bool:
    blob = _blob(tree)
    if not any(n in blob for n in _MATCH_NEEDLES):
        return False
    return "major crush" not in blob  # paid MBM sheet is not a match


def _editable(tree: str) -> Optional[Dict[str, Any]]:
    for n in _parse_compact_nodes(tree):
        if n.get("editable"):
            return n
    return None


def _send_button(tree: str, edit: Optional[Dict[str, Any]]) -> Optional[Tuple[int, int]]:
    c = _tree_id_center(tree, "threadSend", "sendMessageButton", "id/threadSend")
    if c:
        return (int(c[0]), int(c[1]))
    for n in _parse_compact_nodes(tree):
        lab = _label(n).lower()
        nid = str(n.get("id") or "").lower()
        if n.get("editable"):
            continue
        if any(p in lab for p in ("crush", "premium", "boost", "gift")):
            continue
        if lab in ("send", "send message") or ("send" in nid and "crush" not in nid):
            return (int(n["x"]), int(n["y"]))
    # right of the field, same row (free send arrow)
    if edit is not None and edit.get("x2") is not None:
        best = None
        for n in _parse_compact_nodes(tree):
            if n is edit or n.get("x1") is None or not n.get("clickable"):
                continue
            if int(n["x1"]) >= int(edit["x2"]) - 20 and abs(int(n["y"]) - int(edit["y"])) < 80:
                best = (int(n["x"]), int(n["y"]))
        return best
    return None


def safe_close(tree: str) -> Optional[Tuple[int, int, str]]:
    """A free close / dismiss control; never Allow / Buy / Crush / Continue."""
    paid = any(p in _blob(tree) for p in _PAID_NEEDLES)
    best = None
    for n in _parse_compact_nodes(tree):
        lab = _label(n).lower().strip(" .!")
        nid = str(n.get("id") or "").lower()
        if n.get("x") is None:
            continue
        if any(lab == w or lab.startswith(w + " ") for w in _NEVER):
            continue
        if "allow" in lab and "don" not in lab:
            continue
        hit = lab in _SAFE_CLOSE or lab in ("x", "✕", "×") or (
            "close" in nid or nid.endswith("dismiss") or "closebutton" in nid
        )
        if not hit:
            continue
        if paid and lab in ("ok",):
            continue
        best = (int(n["x"]), int(n["y"]), lab or nid)
        if lab in ("not now", "maybe later", "no thanks", "close", "don't allow", "don’t allow"):
            break
    return best


def _act(planner: str, kind: str, step: str, reason: str, **kw: Any) -> Dict[str, Any]:
    a = {"action": kind, "reason": f"{reason} ({planner})", "planner": planner,
         "llm_provider": None, "_no_llm_handoff": True}
    a.update(kw)
    return _fp(a, step)


def handle_interrupt(
    tree: str, hr: Dict[str, Any], text: str, planner: str, **kw: Any
) -> Optional[Dict[str, Any]]:
    """One step for a non-Finder screen during liking, or None (not handled).

    ``kw`` (r49 Tinder): pkg, prefix, chrome (known-screen test), thread_ids,
    app (display name). Defaults are Hily."""
    PKG = kw.get("pkg") or globals()["PKG"]
    prefix = kw.get("prefix") or "hily"
    chrome = kw.get("chrome") or finder_chrome
    thread_ids = kw.get("thread_ids") or ("threadInputFieldText", "threadToolBarName")
    app = kw.get("app") or "Hily"
    pkgs = re.search(r'packages="([^"]*)"', tree or "")
    pk = pkgs.group(1) if pkgs else ""
    # System notification shade / heads-up / permission dialog
    if pk and PKG not in pk and (
        "systemui" in pk or "permissioncontroller" in pk or "packageinstaller" in pk
    ):
        c = safe_close(tree)
        if c and "permission" in pk:
            return _act(planner, "tap", f"{prefix}_int_permission",
                        f"Permission prompt → '{c[2]}' (never Allow)", x=c[0], y=c[1])
        return _act(planner, "press_button", f"{prefix}_int_system_back",
                    f"Close the notification / system sheet → back to {app}", button="back")

    m = hr.setdefault("match", {})
    # ---- match popup (or the thread it opened) ----
    on_thread = any(t in (tree or "") for t in thread_ids)
    if is_match_popup(tree) or (m.get("open") and on_thread):
        if m.get("sent_here"):
            c = safe_close(tree)
            if c and not on_thread:
                return _act(planner, "tap", f"{prefix}_int_match_close",
                            f"Match message sent — close the popup ('{c[2]}')", x=c[0], y=c[1])
            m.clear()
            return _act(planner, "press_button", f"{prefix}_int_match_back",
                        "Match message sent — back to the cards", button="back")
        edit = _editable(tree)
        if edit is None:
            if on_thread and "locked" in _blob(tree):
                m.clear()
                return _act(planner, "press_button", f"{prefix}_int_match_locked",
                            "Match chat is locked — back to Finder", button="back")
            # "Say hi" / "Send a message" button opens the composer
            for n in _parse_compact_nodes(tree):
                lab = _label(n).lower()
                if lab in ("say hi", "say hi!", "say hello", "send a message", "message",
                           "send message", "start chatting", "chat") and n.get("x") is not None:
                    m["open"] = True
                    return _act(planner, "tap", f"{prefix}_int_match_open",
                                f"Match — open the message box ('{lab}')",
                                x=int(n["x"]), y=int(n["y"]))
            c = safe_close(tree)
            if c:
                return _act(planner, "tap", f"{prefix}_int_match_close_nomsg",
                            f"Match without a free message box — close ('{c[2]}')",
                            x=c[0], y=c[1])
            return _act(planner, "press_button", f"{prefix}_int_match_back_nomsg",
                        "Match without a free message box — Back", button="back")
        m["open"] = True
        box = str(edit.get("text") or "").strip()
        hint = str(edit.get("hint") or "").strip()
        if m.get("awaiting"):
            if not box or box == hint:
                m["awaiting"] = False
                m["sent_here"] = True
                hr["match_msgs"] = int(hr.get("match_msgs") or 0) + 1
                return handle_interrupt(tree, hr, text, planner, **kw)
            if int(m.get("retry") or 0) < 1 and box.lower() == text.lower():
                m["retry"] = 1
                xy = _send_button(tree, edit)
                if xy:
                    return _act(planner, "tap", f"{prefix}_int_match_send_retry",
                                "Match message still in the box — Send again", x=xy[0], y=xy[1])
            m.clear()
            m["sent_here"] = True  # give up on this one; never retype
            return handle_interrupt(tree, hr, text, planner, **kw)
        if box.lower() != text.lower():
            if int(m.get("typed") or 0) >= 2:
                m["sent_here"] = True
                return handle_interrupt(tree, hr, text, planner, **kw)
            m["typed"] = int(m.get("typed") or 0) + 1
            return _act(planner, "type", f"{prefix}_int_match_type",
                        f"Match — type '{text}'", text=text, clear=True)
        xy = _send_button(tree, edit)
        if not xy:
            m["sent_here"] = True
            return handle_interrupt(tree, hr, text, planner, **kw)
        m["awaiting"] = True
        return _act(planner, "tap", f"{prefix}_int_match_send",
                    f"Match — send '{text}' (free send)", x=xy[0], y=xy[1])

    if PKG not in pk:
        return None  # another app — caller reopens Hily
    if chrome(tree):
        return None  # on Finder / a Hily tab — caller handles it
    # ---- any other Hily overlay: free close, else Back ----
    c = safe_close(tree)
    if c:
        return _act(planner, "tap", f"{prefix}_int_close",
                    f"Close {app} popup ('{c[2]}') — back to the cards", x=c[0], y=c[1])
    return _act(planner, "press_button", f"{prefix}_int_back",
                f"Unknown {app} screen over the cards — Back (never buy)", button="back")
