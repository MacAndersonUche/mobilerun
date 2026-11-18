"""Deterministic DM / chat fast-paths for Social + Dating apps.

Covers: WhatsApp, Instagram, Messenger, Telegram, Tinder, Bumble, Hinge.
Flow (per app): open → inbox/DMs → search → open chat → compose → type → send → verify.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Minimum useful a11y nodes before vision fallback is preferred
MIN_USEFUL_TREE_NODES = 15

# App profiles for open → inbox → search → chat → type → send
DM_APP_PROFILES: Dict[str, Dict[str, Any]] = {
    "whatsapp": {
        "aliases": ("whatsapp", "wa"),
        "package": "com.whatsapp",
        "pkg_markers": ("whatsapp",),
        "open_label": "WhatsApp",
        "inbox_labels": ("Chats", "New chat"),
        "search_labels": ("Search", "search"),
        "search_fallback": (980, 160),
        "compose_labels": ("Type a message", "Message", "Write a message"),
        "send_labels": ("Send",),
        "send_fallback": (1000, 2280),
        "compose_fallback": (540, 2250),
    },
    "instagram": {
        "aliases": ("instagram", "ig"),
        "package": "com.instagram.android",
        "pkg_markers": ("instagram",),
        "open_label": "Instagram",
        "inbox_labels": (
            "Messages",
            "Direct",
            "Messenger",
            "Open direct message",
            "Inbox",
            "New message",
        ),
        "search_labels": ("Search", "Search…", "Search...", "To:"),
        "search_fallback": (980, 160),
        "compose_labels": ("Message…", "Message...", "Message", "Write a message"),
        "send_labels": ("Send", "Send message"),
        "send_fallback": (1000, 2280),
        "compose_fallback": (540, 2250),
    },
    "messenger": {
        "aliases": ("messenger", "facebook messenger", "fb messenger"),
        "package": "com.facebook.orca",
        "pkg_markers": ("orca", "messenger"),
        "open_label": "Messenger",
        "inbox_labels": ("Chats", "Messages", "New message", "Compose"),
        "search_labels": ("Search", "Search…", "Search Messenger"),
        "search_fallback": (540, 200),
        "compose_labels": ("Aa", "Message", "Write a message", "Send a message"),
        "send_labels": ("Send", "Send message"),
        "send_fallback": (1000, 2280),
        "compose_fallback": (540, 2250),
    },
    "telegram": {
        "aliases": ("telegram", "tg"),
        "package": "org.telegram.messenger",
        "pkg_markers": ("telegram",),
        "open_label": "Telegram",
        "inbox_labels": ("Chats", "New Message", "New message"),
        "search_labels": ("Search", "Search…"),
        "search_fallback": (980, 160),
        "compose_labels": ("Message", "Write a message"),
        "send_labels": ("Send",),
        "send_fallback": (1000, 2280),
        "compose_fallback": (540, 2250),
    },
    "tinder": {
        "aliases": ("tinder",),
        "package": "com.tinder",
        "pkg_markers": ("tinder",),
        "open_label": "Tinder",
        "inbox_labels": ("Chat", "Chats", "Messages", "Matches", "Inbox"),
        "search_labels": ("Search", "Search matches", "Search…"),
        "search_fallback": (540, 200),
        "compose_labels": (
            "Type a message",
            "Message",
            "Send a message",
            "Say something",
        ),
        "send_labels": ("Send",),
        "send_fallback": (1000, 2280),
        "compose_fallback": (540, 2250),
    },
    "bumble": {
        "aliases": ("bumble",),
        "package": "com.bumble.app",
        "pkg_markers": ("bumble",),
        "open_label": "Bumble",
        "inbox_labels": ("Messages", "Connections", "Chats", "Inbox"),
        "search_labels": ("Search", "Search…"),
        "search_fallback": (980, 160),
        "compose_labels": ("Type a message", "Message", "Say something"),
        "send_labels": ("Send",),
        "send_fallback": (1000, 2280),
        "compose_fallback": (540, 2250),
    },
    "hinge": {
        "aliases": ("hinge",),
        "package": "co.hinge.app",
        "pkg_markers": ("hinge",),
        "open_label": "Hinge",
        "inbox_labels": ("Matches", "Messages", "Chats", "Liked You", "Inbox"),
        "search_labels": ("Search", "Search…"),
        "search_fallback": (980, 160),
        "compose_labels": (
            "Type a message",
            "Message",
            "Your message",
            "Say something",
        ),
        "send_labels": ("Send",),
        "send_fallback": (1000, 2280),
        "compose_fallback": (540, 2250),
    },
}


def tree_node_count(tree: str) -> int:
    low = (tree or "").lower()
    return low.count("<n ") + low.count("<node ")


def tree_is_sparse(tree: str, nodes: Optional[int] = None) -> bool:
    """True when a11y dump is too thin for reliable planning (Compose/Flutter)."""
    if nodes is not None and nodes > 0:
        return nodes < MIN_USEFUL_TREE_NODES
    n = tree_node_count(tree)
    if n == 0:
        # Empty / hollow hierarchy
        low = (tree or "").lower()
        if not tree or 'empty="true"' in low or len(tree) < 80:
            return True
        return True
    return n < MIN_USEFUL_TREE_NODES


def _tree_node_center(tree: str, *needles: str) -> Optional[Tuple[int, int]]:
    low = (tree or "").lower()
    for needle in needles:
        n = (needle or "").lower().strip()
        if not n:
            continue
        for pat in (
            rf'<(?:n|node)\b[^>]*(?:t|d|h|text|content-desc|contentDescription)="[^"]*{re.escape(n)}[^"]*"[^>]*\bxy="(\d+),(\d+)"',
            rf'<(?:n|node)\b[^>]*\bxy="(\d+),(\d+)"[^>]*(?:t|d|h|text|content-desc|contentDescription)="[^"]*{re.escape(n)}[^"]*"',
            rf'<(?:n|node)\b[^>]*(?:t|d|h|text|content-desc)="[^"]*{re.escape(n)}[^"]*"[^>]*\bb="(\d+),(\d+),(\d+),(\d+)"',
            rf'<(?:n|node)\b[^>]*\bb="(\d+),(\d+),(\d+),(\d+)"[^>]*(?:t|d|h|text|content-desc)="[^"]*{re.escape(n)}[^"]*"',
            rf'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"[^>]*(?:text|content-desc)="[^"]*{re.escape(n)}[^"]*"',
            rf'(?:text|content-desc)="[^"]*{re.escape(n)}[^"]*"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
        ):
            m = re.search(pat, low, re.I)
            if not m:
                continue
            groups = [int(g) for g in m.groups() if g is not None]
            if len(groups) == 2:
                return (groups[0], groups[1])
            if len(groups) >= 4:
                x1, y1, x2, y2 = groups[:4]
                return ((x1 + x2) // 2, (y1 + y2) // 2)
    return None


def _tree_editable_center(tree: str) -> Optional[Tuple[int, int]]:
    low = (tree or "").lower()
    for pat in (
        r'<(?:n|node)\b[^>]*\be="?1"?[^>]*\bxy="(\d+),(\d+)"',
        r'<(?:n|node)\b[^>]*\bxy="(\d+),(\d+)"[^>]*\be="?1"?',
        r'<(?:n|node)\b[^>]*edittext[^>]*\bxy="(\d+),(\d+)"',
        r'<(?:n|node)\b[^>]*\bb="(\d+),(\d+),(\d+),(\d+)"[^>]*\be="?1"?',
        r'<(?:n|node)\b[^>]*\be="?1"?[^>]*\bb="(\d+),(\d+),(\d+),(\d+)"',
    ):
        m = re.search(pat, low, re.I)
        if not m:
            continue
        groups = [int(g) for g in m.groups() if g is not None]
        if len(groups) == 2:
            return (groups[0], groups[1])
        if len(groups) >= 4:
            x1, y1, x2, y2 = groups[:4]
            return ((x1 + x2) // 2, (y1 + y2) // 2)
    return None


def _is_launcher_package(package: str) -> bool:
    pkg = (package or "").lower()
    return bool(pkg) and "launcher" in pkg


def detect_dm_app(instruction: str) -> Optional[str]:
    """Return profile key if instruction names a supported DM app."""
    low = (instruction or "").lower()
    # Longer aliases first (facebook messenger before messenger)
    ranked: List[Tuple[int, str]] = []
    for key, prof in DM_APP_PROFILES.items():
        for alias in prof["aliases"]:
            if re.search(rf"(?<![a-z]){re.escape(alias)}(?![a-z])", low):
                ranked.append((len(alias), key))
                break
    if not ranked:
        return None
    ranked.sort(reverse=True)
    return ranked[0][1]


def parse_dm_instruction(instruction: str) -> Optional[Dict[str, str]]:
    """Extract {app, contact, message} from a DM send goal."""
    text = (instruction or "").strip()
    if not text:
        return None
    app_key = detect_dm_app(text)
    if not app_key:
        return None
    if not any(
        k in text.lower()
        for k in ("message", "msg", "text", "chat", "say", "send", "dm")
    ):
        return None
    aliases = DM_APP_PROFILES[app_key]["aliases"]
    alias_alt = "|".join(re.escape(a) for a in sorted(aliases, key=len, reverse=True))
    patterns = (
        rf"(?:go\s+on\s+|open\s+|launch\s+)?(?:{alias_alt})\s+"
        rf"(?:message|msg|text|dm|chat(?:\s+with)?)\s+(.+?)\s+"
        rf"(?:and\s+)?(?:say|send|tell)\s+(.+)$",
        rf"(?:{alias_alt})[,:]?\s+(?:message|msg|text|dm)\s+(.+?)\s+"
        rf"(?:and\s+)?(?:say|send)\s+(.+)$",
        rf"(?:message|msg|text|dm)\s+(.+?)\s+on\s+(?:{alias_alt})\s+"
        rf"(?:and\s+)?(?:say|send)\s+(.+)$",
        rf"(?:{alias_alt})\s+(.+?)\s+(?:and\s+)?(?:say|send)\s+(.+)$",
    )
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if not m:
            continue
        contact = re.sub(r"\s+", " ", m.group(1)).strip(" .,\"'")
        message = re.sub(r"\s+", " ", m.group(2)).strip(" .,\"'")
        contact = re.sub(
            r"^(?:message|msg|text|dm|chat(?:\s+with)?)\s+",
            "",
            contact,
            flags=re.I,
        ).strip()
        if contact and message and len(contact) <= 80 and len(message) <= 500:
            return {"app": app_key, "contact": contact, "message": message}
    return None


def _app_foreground(pkg: str, tree: str, profile: Dict[str, Any]) -> bool:
    pkg_l = (pkg or "").lower()
    markers: Sequence[str] = profile.get("pkg_markers") or ()
    if any(m in pkg_l for m in markers):
        return True
    if _is_launcher_package(pkg_l):
        return False
    tl = (tree or "").lower()
    package = str(profile.get("package") or "").lower()
    if package and (f'p="{package}"' in tl or f'packages="{package}"' in tl):
        return True
    return any(m in pkg_l for m in markers)


def _hist_has_type(history: List[str], text: str) -> bool:
    t = text.lower()
    return any(
        t in str(h).lower() and ("type" in str(h).lower() or "typed" in str(h).lower())
        for h in history[-16:]
    )


def heuristic_dm_send(
    instruction: str,
    ui_tree: str,
    history: List[str],
    package: str = "",
    *,
    goal_satisfied=None,
) -> Optional[Dict[str, Any]]:
    """Generic DM fast-path. Returns an action dict or None."""
    parsed = parse_dm_instruction(instruction)
    if not parsed:
        return None
    app_key = parsed["app"]
    profile = DM_APP_PROFILES[app_key]
    contact = parsed["contact"]
    message = parsed["message"]
    planner = f"{app_key}_heuristic"
    hist = " ".join(history[-16:]).lower()
    pkg = (package or "").lower()
    tl = (ui_tree or "").lower()
    open_label = profile["open_label"]
    open_l = open_label.lower()
    fg = _app_foreground(pkg, ui_tree, profile)

    if goal_satisfied:
        sat = goal_satisfied(instruction, ui_tree, package)
        # goal_satisfied already requires marker in a text/desc attribute
        if sat:
            return {
                "action": "done",
                "reason": sat,
                "planner": planner,
                "llm_provider": None,
            }

    if "isn't responding" in tl or "not responding" in tl:
        return {
            "action": "tap",
            "x": 540,
            "y": 1395,
            "reason": f"Dismiss ANR Wait ({planner})",
            "planner": planner,
            "llm_provider": None,
        }

    opened = (
        f"opened {open_l}" in hist
        or f"open_app({open_l})" in hist
        or f"open_app({app_key})" in hist
        or (f"open_ok" in hist and (open_l in hist or app_key in hist))
        or fg
    )
    if not opened:
        return {
            "action": "open_app",
            "app": open_label,
            "reason": f"Open {open_label} ({planner})",
            "planner": planner,
            "llm_provider": None,
        }

    typed_contact = _hist_has_type(history, contact)
    tapped_contact = any(
        contact.lower() in str(h).lower()
        and (
            "tap contact" in str(h).lower()
            or "select contact" in str(h).lower()
            or "matching" in str(h).lower()
            or "open chat" in str(h).lower()
        )
        for h in history[-16:]
    )
    tapped_inbox = (
        any(
            any(lab.lower() in str(h).lower() for lab in profile["inbox_labels"])
            and ("tap" in str(h).lower() or "inbox" in str(h).lower())
            for h in history[-16:]
        )
        or "tap inbox" in hist
        or "open dms" in hist
        or "open inbox" in hist
    )
    tapped_search = "tap search" in hist or (
        "search" in hist and "tap(" in hist and (open_l in hist or app_key in hist)
    )
    typed_message = _hist_has_type(history, message)
    tapped_send = any(
        "tap send" in str(h).lower() or f"send ({planner}" in str(h).lower()
        for h in history[-16:]
    )
    focused_compose = any(
        "compose" in str(h).lower() or "message field" in str(h).lower()
        for h in history[-16:]
    )

    # 0) Enter DMs / inbox when still on feed/home (Instagram / dating)
    needs_inbox = bool(profile.get("inbox_labels")) and app_key != "whatsapp"
    if needs_inbox and not tapped_inbox and not typed_contact and not tapped_search:
        # If search already visible, skip inbox hop
        if not _tree_node_center(ui_tree, *tuple(profile["search_labels"])):
            c = _tree_node_center(ui_tree, *tuple(profile["inbox_labels"]))
            if c:
                return {
                    "action": "tap",
                    "x": c[0],
                    "y": c[1],
                    "reason": f"Open inbox/DMs ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                }
            # Dating apps: often bottom-nav Messages — try common coords
            if app_key in ("tinder", "bumble", "hinge", "instagram"):
                return {
                    "action": "tap",
                    "x": 860 if app_key == "instagram" else 900,
                    "y": 150 if app_key == "instagram" else 2280,
                    "reason": f"Open inbox coords fallback ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                }

    # 1) Search
    if not typed_contact and not tapped_search:
        c = _tree_node_center(ui_tree, *tuple(profile["search_labels"]))
        if c:
            return {
                "action": "tap",
                "x": c[0],
                "y": c[1],
                "reason": f"Tap Search ({planner})",
                "planner": planner,
                "llm_provider": None,
            }
        fx, fy = profile["search_fallback"]
        return {
            "action": "tap",
            "x": fx,
            "y": fy,
            "reason": f"Tap Search coords fallback ({planner})",
            "planner": planner,
            "llm_provider": None,
        }

    # 2) Type contact
    if (tapped_search or _tree_editable_center(ui_tree)) and not typed_contact:
        return {
            "action": "type",
            "text": contact,
            "reason": f"Type contact '{contact}' ({planner})",
            "planner": planner,
            "llm_provider": None,
        }

    # 3) Tap matching result / open chat
    if typed_contact and not tapped_contact and not typed_message:
        tokens = [contact] + ([contact.split()[0]] if " " in contact else [])
        c = _tree_node_center(ui_tree, *tokens)
        if c:
            return {
                "action": "tap",
                "x": c[0],
                "y": c[1],
                "reason": f"Tap matching contact '{contact}' ({planner})",
                "planner": planner,
                "llm_provider": None,
            }
        if hist.count("swipe") < 2:
            return {
                "action": "swipe",
                "x1": 540,
                "y1": 1600,
                "x2": 540,
                "y2": 800,
                "reason": f"Scroll contact results ({planner})",
                "planner": planner,
                "llm_provider": None,
            }
        return {
            "action": "tap",
            "x": 540,
            "y": 420,
            "reason": f"Tap first search result for '{contact}' ({planner})",
            "planner": planner,
            "llm_provider": None,
        }

    # 4) Focus compose
    if (tapped_contact or typed_contact) and not typed_message and not focused_compose:
        ec = _tree_editable_center(ui_tree)
        c = _tree_node_center(ui_tree, *tuple(profile["compose_labels"]))
        if ec or c:
            x, y = ec or c
            return {
                "action": "tap",
                "x": x,
                "y": y,
                "reason": f"Focus compose Message field ({planner})",
                "planner": planner,
                "llm_provider": None,
            }
        cx, cy = profile["compose_fallback"]
        return {
            "action": "tap",
            "x": cx,
            "y": cy,
            "reason": f"Focus compose coords fallback ({planner})",
            "planner": planner,
            "llm_provider": None,
        }

    # 5) Type message
    if (focused_compose or (typed_contact and tapped_contact)) and not typed_message:
        return {
            "action": "type",
            "text": message,
            "reason": f"Type message '{message}' ({planner})",
            "planner": planner,
            "llm_provider": None,
        }

    # 6) Send
    if typed_message and not tapped_send:
        c = _tree_node_center(ui_tree, *tuple(profile["send_labels"]))
        sx, sy = profile["send_fallback"]
        x, y = c if c else (sx, sy)
        return {
            "action": "tap",
            "x": x,
            "y": y,
            "reason": f"Tap Send ({planner})",
            "planner": planner,
            "llm_provider": None,
        }

    # 7) Verify / re-send
    if tapped_send:
        if goal_satisfied:
            sat2 = goal_satisfied(instruction, ui_tree, package)
            if sat2:
                return {
                    "action": "done",
                    "reason": sat2,
                    "planner": planner,
                    "llm_provider": None,
                }
        if hist.count("tap send") + hist.count("re-tap send") < 3:
            c = _tree_node_center(ui_tree, *tuple(profile["send_labels"]))
            sx, sy = profile["send_fallback"]
            x, y = c if c else (sx, sy)
            return {
                "action": "tap",
                "x": x,
                "y": y,
                "reason": f"Re-tap Send ({planner})",
                "planner": planner,
                "llm_provider": None,
            }

    if fg:
        ec = _tree_editable_center(ui_tree)
        if ec and not typed_message:
            return {
                "action": "tap",
                "x": ec[0],
                "y": ec[1],
                "reason": f"Continue compose ({planner})",
                "planner": planner,
                "llm_provider": None,
            }
        c = _tree_node_center(ui_tree, *tuple(profile["search_labels"]))
        if c and not typed_contact:
            return {
                "action": "tap",
                "x": c[0],
                "y": c[1],
                "reason": f"Retry Search ({planner})",
                "planner": planner,
                "llm_provider": None,
            }
    return None
