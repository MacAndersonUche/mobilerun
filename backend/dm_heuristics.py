"""Deterministic DM / chat fast-paths for Social + Dating apps.

Covers: WhatsApp, Instagram, Messenger, Telegram, Tinder, Bumble, Hinge.
Flow: open → inbox/DMs → search → type contact → tap result row → VERIFY chat
(header + compose) → type message into compose only → send (or dry-run stop).
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
        "new_chat_labels": ("New chat", "New Chat"),
        "search_labels": ("Search", "search", "Search…", "Search..."),
        "search_ids": (
            "com.whatsapp:id/menuitem_search",
            "com.whatsapp:id/search_src_text",
            "com.whatsapp:id/search_input",
            "id/menuitem_search",
            "id/search_src_text",
        ),
        "search_fallback": (980, 160),
        "result_ids": (
            "com.whatsapp:id/contact_row_container",
            "com.whatsapp:id/conversations_row_contact_name",
            "com.whatsapp:id/resultlist",
            "id/contact_row_container",
        ),
        "header_ids": (
            "com.whatsapp:id/conversation_contact_name",
            "com.whatsapp:id/toolbar",
            "id/conversation_contact_name",
        ),
        "compose_labels": ("Type a message", "Message", "Write a message"),
        "compose_ids": ("com.whatsapp:id/entry", "id/entry", ":id/entry"),
        "send_labels": ("Send",),
        "send_ids": ("com.whatsapp:id/send", "id/send", ":id/send"),
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
        "new_chat_labels": ("New message", "New Message"),
        "search_labels": ("Search", "Search…", "Search...", "To:"),
        "search_ids": (
            "com.instagram.android:id/search_edit_text",
            "com.instagram.android:id/action_bar_search_edit_text",
            "id/search_edit_text",
        ),
        "search_fallback": (980, 160),
        "result_ids": (
            "com.instagram.android:id/row_inbox_container",
            "com.instagram.android:id/row_search_user_container",
            "id/row_inbox_container",
        ),
        "header_ids": (
            "com.instagram.android:id/thread_title",
            "com.instagram.android:id/action_bar_title",
            "id/thread_title",
        ),
        "compose_labels": ("Message…", "Message...", "Message", "Write a message"),
        "compose_ids": (
            "com.instagram.android:id/row_thread_composer_edittext",
            "com.instagram.android:id/message_edit_text",
            "id/row_thread_composer_edittext",
        ),
        "send_labels": ("Send", "Send message"),
        "send_ids": (
            "com.instagram.android:id/row_thread_composer_button_send",
            "id/row_thread_composer_button_send",
        ),
        "send_fallback": (1000, 2280),
        "compose_fallback": (540, 2250),
    },
    "messenger": {
        "aliases": ("messenger", "facebook messenger", "fb messenger"),
        "package": "com.facebook.orca",
        "pkg_markers": ("orca", "messenger"),
        "open_label": "Messenger",
        "inbox_labels": ("Chats", "Messages", "New message", "Compose"),
        "new_chat_labels": ("New message", "Compose"),
        "search_labels": ("Search", "Search…", "Search Messenger"),
        "search_ids": (
            "com.facebook.orca:id/search_edit_text",
            "id/search_edit_text",
        ),
        "search_fallback": (540, 200),
        "result_ids": ("com.facebook.orca:id/thread_list_item",),
        "header_ids": ("com.facebook.orca:id/thread_title_view",),
        "compose_labels": ("Aa", "Message", "Write a message", "Send a message"),
        "compose_ids": (
            "com.facebook.orca:id/composer_text",
            "com.facebook.orca:id/composer_edit_text",
            "id/composer_text",
        ),
        "send_labels": ("Send", "Send message"),
        "send_ids": ("com.facebook.orca:id/composer_send_button", "id/composer_send_button"),
        "send_fallback": (1000, 2280),
        "compose_fallback": (540, 2250),
    },
    "telegram": {
        "aliases": ("telegram", "tg"),
        "package": "org.telegram.messenger",
        "pkg_markers": ("telegram",),
        "open_label": "Telegram",
        "inbox_labels": ("Chats", "New Message", "New message"),
        "new_chat_labels": ("New Message", "New message"),
        "search_labels": ("Search", "Search…"),
        "search_ids": (
            "org.telegram.messenger:id/search_field",
            "id/search_field",
        ),
        "search_fallback": (980, 160),
        "result_ids": (),
        "header_ids": ("org.telegram.messenger:id/action_bar_title",),
        "compose_labels": ("Message", "Write a message"),
        "compose_ids": (
            "org.telegram.messenger:id/chat_message_edit",
            "id/chat_message_edit",
        ),
        "send_labels": ("Send",),
        "send_ids": (
            "org.telegram.messenger:id/chat_send_button",
            "id/chat_send_button",
        ),
        "send_fallback": (1000, 2280),
        "compose_fallback": (540, 2250),
    },
    "tinder": {
        "aliases": ("tinder",),
        "package": "com.tinder",
        "pkg_markers": ("tinder",),
        "open_label": "Tinder",
        "inbox_labels": ("Chat", "Chats", "Messages", "Matches", "Inbox"),
        "new_chat_labels": ("Matches", "Chat"),
        "search_labels": ("Search", "Search matches", "Search…"),
        "search_ids": (),
        "search_fallback": (540, 200),
        "result_ids": (),
        "header_ids": (),
        "compose_labels": (
            "Type a message",
            "Message",
            "Send a message",
            "Say something",
        ),
        "compose_ids": (),
        "send_labels": ("Send",),
        "send_ids": (),
        "send_fallback": (1000, 2280),
        "compose_fallback": (540, 2250),
    },
    "bumble": {
        "aliases": ("bumble",),
        "package": "com.bumble.app",
        "pkg_markers": ("bumble",),
        "open_label": "Bumble",
        "inbox_labels": ("Messages", "Connections", "Chats", "Inbox"),
        "new_chat_labels": ("Messages", "Connections"),
        "search_labels": ("Search", "Search…"),
        "search_ids": (),
        "search_fallback": (980, 160),
        "result_ids": (),
        "header_ids": (),
        "compose_labels": ("Type a message", "Message", "Say something"),
        "compose_ids": (),
        "send_labels": ("Send",),
        "send_ids": (),
        "send_fallback": (1000, 2280),
        "compose_fallback": (540, 2250),
    },
    "hinge": {
        "aliases": ("hinge",),
        "package": "co.hinge.app",
        "pkg_markers": ("hinge",),
        "open_label": "Hinge",
        "inbox_labels": ("Matches", "Messages", "Chats", "Liked You", "Inbox"),
        "new_chat_labels": ("Matches", "Liked You"),
        "search_labels": ("Search", "Search…"),
        "search_ids": (),
        "search_fallback": (980, 160),
        "result_ids": (),
        "header_ids": (),
        "compose_labels": (
            "Type a message",
            "Message",
            "Your message",
            "Say something",
        ),
        "compose_ids": (),
        "send_labels": ("Send",),
        "send_ids": (),
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


def _tree_id_center(tree: str, *id_needles: str) -> Optional[Tuple[int, int]]:
    """Locate a node by resource-id suffix (e.g. com.whatsapp:id/entry)."""
    for n in _parse_compact_nodes(tree):
        vid = str(n.get("id") or "").lower()
        if not vid:
            continue
        for needle in id_needles:
            want = (needle or "").lower().strip()
            if not want:
                continue
            if vid == want or vid.endswith(want) or want in vid:
                return (int(n["x"]), int(n["y"]))
    return None


def find_compose_center(
    tree: str,
    compose_labels: Sequence[str],
    compose_ids: Sequence[str] = (),
    search_labels: Sequence[str] = (),
) -> Optional[Tuple[int, int]]:
    """Prefer WhatsApp entry id, then Message hint, then bottom editable."""
    c = _tree_id_center(tree, *tuple(compose_ids))
    if c:
        return c
    c = _tree_node_center(tree, *tuple(compose_labels))
    if c:
        return c
    for n in _parse_compact_nodes(tree):
        if not n.get("editable"):
            continue
        if _is_searchish_node(n, search_labels):
            continue
        hint = str(n.get("hint") or "").lower()
        label = str(n.get("label") or "").lower()
        if "message" in hint or "message" in label or n.get("y", 0) > 1800:
            return (int(n["x"]), int(n["y"]))
    return None


def find_send_center(
    tree: str, send_labels: Sequence[str], send_ids: Sequence[str] = ()
) -> Optional[Tuple[int, int]]:
    c = _tree_id_center(tree, *tuple(send_ids))
    if c:
        return c
    return _tree_node_center(tree, *tuple(send_labels))


_NODE_TAG_RE = re.compile(r"<(?:n|node)\b([^>]*)/?>", re.I)


def _attr(blob: str, *names: str) -> str:
    for name in names:
        m = re.search(rf'\b{re.escape(name)}="([^"]*)"', blob, re.I)
        if m:
            return m.group(1)
    return ""


def _parse_compact_nodes(tree: str) -> List[Dict[str, Any]]:
    """Parse compact a11y dump nodes into dicts with center/flags."""
    out: List[Dict[str, Any]] = []
    for m in _NODE_TAG_RE.finditer(tree or ""):
        attrs = m.group(1)
        text = _attr(attrs, "t", "text")
        desc = _attr(attrs, "d", "content-desc", "contentDescription")
        hint = _attr(attrs, "h", "hint")
        xy = _attr(attrs, "xy")
        b = _attr(attrs, "b", "bounds")
        editable = _attr(attrs, "e") in ("1", "true", "True")
        clickable = _attr(attrs, "c") in ("1", "true", "True")
        cx = cy = None
        if xy and "," in xy:
            try:
                cx, cy = [int(p) for p in xy.split(",")[:2]]
            except ValueError:
                cx = cy = None
        if (cx is None or cy is None) and b:
            nums = re.findall(r"\d+", b)
            if len(nums) >= 4:
                x1, y1, x2, y2 = (int(n) for n in nums[:4])
                cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        if cx is None or cy is None:
            continue
        label = " ".join(p for p in (text, desc, hint) if p).strip()
        view_id = _attr(attrs, "i", "resource-id", "viewIdResourceName")
        cls = _attr(attrs, "cls", "class", "className")
        focused = _attr(attrs, "f") in ("1", "true", "True")
        out.append(
            {
                "text": text,
                "desc": desc,
                "hint": hint,
                "label": label,
                "id": view_id,
                "cls": cls,
                "x": cx,
                "y": cy,
                "editable": editable,
                "clickable": clickable,
                "focused": focused,
            }
        )
    return out


def _fuzzy_score(needle: str, hay: str) -> float:
    """Simple token-overlap fuzzy score in [0, 1]."""
    n = re.sub(r"\s+", " ", (needle or "").strip().lower())
    h = re.sub(r"\s+", " ", (hay or "").strip().lower())
    if not n or not h:
        return 0.0
    if n == h:
        return 1.0
    if n in h or h in n:
        return 0.92
    nt = [t for t in re.split(r"[^\w]+", n) if t]
    ht = set(t for t in re.split(r"[^\w]+", h) if t)
    if not nt:
        return 0.0
    hit = sum(1 for t in nt if t in ht)
    return hit / len(nt)


def _is_searchish_node(node: Dict[str, Any], search_labels: Sequence[str]) -> bool:
    if node.get("editable"):
        hint = (node.get("hint") or "").lower()
        label = (node.get("label") or "").lower()
        if any(s.lower() in hint or s.lower() in label for s in search_labels):
            return True
        if "search" in hint or "search" in label or hint.startswith("to"):
            return True
        # Top-of-screen editable is almost always the search box after query type
        if int(node.get("y") or 0) < 280:
            return True
    return False


def find_contact_result_center(
    tree: str,
    contact: str,
    *,
    search_labels: Sequence[str] = (),
) -> Optional[Tuple[int, int]]:
    """Best fuzzy match for a contact *result row* — never the search EditText."""
    nodes = _parse_compact_nodes(tree)
    if not nodes:
        # Fallback: old center search but only if we can exclude editables later
        return None
    candidates: List[Tuple[float, int, Dict[str, Any]]] = []
    for node in nodes:
        if _is_searchish_node(node, search_labels):
            continue
        score = _fuzzy_score(contact, node.get("label") or "")
        if score < 0.5:
            # Also try first token (first name)
            first = (contact.split() or [""])[0]
            if first and len(first) >= 3:
                score = max(score, _fuzzy_score(first, node.get("label") or "") * 0.85)
        if score < 0.5:
            continue
        # Prefer clickable list rows below the search bar
        y = int(node.get("y") or 0)
        if y < 260:
            score *= 0.4
        if node.get("clickable"):
            score += 0.05
        candidates.append((score, y, node))
    if not candidates:
        return None
    candidates.sort(key=lambda t: (-t[0], t[1]))
    best = candidates[0][2]
    return (int(best["x"]), int(best["y"]))


def _label_matches_compose(blob: str, compose_labels: Sequence[str]) -> bool:
    """Match compose hints without treating nav 'Messages' as a compose box."""
    b = (blob or "").strip().lower()
    if not b:
        return False
    # Exact / prefix-ish compose phrases
    for lab in compose_labels:
        l = lab.lower().strip()
        if not l:
            continue
        if b == l or b.startswith(l) or l.startswith(b):
            return True
        # Allow "Type a message" inside longer hint strings
        if " " in l and l in b:
            return True
    if b in ("aa", "say something") or b.startswith("type a message"):
        return True
    # Single word "message" / "message…" only — not "Messages" inbox tab
    if re.fullmatch(r"message[.…]*", b):
        return True
    return False


def compose_field_present(tree: str, compose_labels: Sequence[str]) -> bool:
    # Prefer editable nodes with compose-like hints (real message box)
    for node in _parse_compact_nodes(tree):
        if not node.get("editable"):
            continue
        blob = f"{node.get('hint') or ''} {node.get('label') or ''}".strip()
        if _label_matches_compose(blob, compose_labels):
            return True
        # Bottom-of-screen editable without "search" is almost always compose
        y = int(node.get("y") or 0)
        low = blob.lower()
        if y > 1600 and "search" not in low and "to:" not in low:
            return True
    return False


def chat_screen_verified(
    tree: str,
    contact: str,
    compose_labels: Sequence[str],
) -> bool:
    """True when conversation header shows the contact AND a compose field exists."""
    if not compose_field_present(tree, compose_labels):
        return False
    nodes = _parse_compact_nodes(tree)
    # Search screen still active?
    searchish = [
        n
        for n in nodes
        if n.get("editable")
        and (
            "search" in f"{n.get('hint')} {n.get('label')}".lower()
            or (
                int(n.get("y") or 0) < 280
                and "message" not in f"{n.get('hint')} {n.get('label')}".lower()
            )
        )
    ]
    if searchish:
        return False
    # Header / title match for contact (top band, non-editable)
    for n in nodes:
        if n.get("editable"):
            continue
        y = int(n.get("y") or 0)
        if y > 320:
            continue
        if _fuzzy_score(contact, n.get("label") or "") >= 0.6:
            return True
    # Soft pass: compose present and no search field
    return True


def outgoing_bubble_present(tree: str, message: str) -> bool:
    """True when the typed message appears as an outgoing bubble in the tree.

    Heuristic: message text is visible on a non-editable node in the lower
    half of the screen (chat transcript), not only in the compose EditText.
    """
    needle = (message or "").strip()
    if len(needle) < 2:
        return False
    low_needle = needle.lower()
    for n in _parse_compact_nodes(tree):
        if n.get("editable"):
            continue
        blob = f"{n.get('label') or ''} {n.get('hint') or ''}".lower()
        if low_needle not in blob and low_needle[:12] not in blob:
            continue
        y = int(n.get("y") or 0)
        if y > 700:  # below header / search
            return True
    return False


def focused_is_compose_not_search(
    tree: str, compose_labels: Sequence[str], search_labels: Sequence[str]
) -> bool:
    """Refuse typing when the only editable is a search/recipient field."""
    nodes = _parse_compact_nodes(tree)
    editables = [n for n in nodes if n.get("editable")]
    if not editables:
        # Compose might be described only via hint labels without e=1
        return compose_field_present(tree, compose_labels)
    # Prefer bottom-of-screen message boxes
    for n in editables:
        blob = f"{n.get('hint')} {n.get('label')}".lower()
        y = int(n.get("y") or 0)
        if any(lab.lower() in blob for lab in compose_labels) or (
            ("message" in blob or "say something" in blob) and y > 1600
        ):
            return True
    # If every editable looks like search / top bar → not compose
    if all(_is_searchish_node(n, search_labels) for n in editables):
        return False
    # Bottom editable without search hint counts as compose
    bottom = [n for n in editables if int(n.get("y") or 0) > 1600]
    return bool(bottom)


def _is_launcher_package(package: str) -> bool:
    pkg = (package or "").lower()
    return bool(pkg) and "launcher" in pkg


def detect_dm_app(instruction: str) -> Optional[str]:
    """Return profile key if instruction names a supported DM app."""
    low = (instruction or "").lower()
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
    """Extract {app, contact, message} from a DM send goal.

    Supports phrasings like:
      whatsapp find and message Precious Achalugo tell her hi baby
      go on whatsapp message X and say Y
    """
    text = (instruction or "").strip()
    if not text:
        return None
    app_key = detect_dm_app(text)
    if not app_key:
        return None
    if not any(
        k in text.lower()
        for k in ("message", "msg", "text", "chat", "say", "send", "dm", "tell")
    ):
        return None
    aliases = DM_APP_PROFILES[app_key]["aliases"]
    alias_alt = "|".join(re.escape(a) for a in sorted(aliases, key=len, reverse=True))
    say = r"(?:say|send|tell(?:\s+(?:her|him|them))?)"
    patterns = (
        # find and message X tell her Y
        rf"(?:go\s+on\s+|open\s+|launch\s+)?(?:{alias_alt})\s+"
        rf"(?:find\s+(?:and\s+)?)?(?:message|msg|text|dm|chat(?:\s+with)?)\s+(.+?)\s+"
        rf"(?:and\s+)?{say}\s+(.+)$",
        rf"(?:{alias_alt})[,:]?\s+(?:find\s+(?:and\s+)?)?(?:message|msg|text|dm)\s+(.+?)\s+"
        rf"(?:and\s+)?{say}\s+(.+)$",
        rf"(?:message|msg|text|dm)\s+(.+?)\s+on\s+(?:{alias_alt})\s+"
        rf"(?:and\s+)?{say}\s+(.+)$",
        rf"(?:{alias_alt})\s+(.+?)\s+(?:and\s+)?{say}\s+(.+)$",
    )
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if not m:
            continue
        contact = re.sub(r"\s+", " ", m.group(1)).strip(" .,\"'")
        message = re.sub(r"\s+", " ", m.group(2)).strip(" .,\"'")
        contact = re.sub(
            r"^(?:find\s+(?:and\s+)?)?(?:message|msg|text|dm|chat(?:\s+with)?)\s+",
            "",
            contact,
            flags=re.I,
        ).strip()
        # Strip instruction leftovers from message body
        message = re.sub(r"^(?:her|him|them)\s+", "", message, flags=re.I).strip(
            " .,\"'"
        )
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


def _fp(action: Dict[str, Any], step: str) -> Dict[str, Any]:
    """Tag heuristic actions for steps_detail / debugging."""
    action = dict(action)
    action["fastpath_step"] = step
    action["_fastpath_step"] = step
    return action


def heuristic_dm_send(
    instruction: str,
    ui_tree: str,
    history: List[str],
    package: str = "",
    *,
    goal_satisfied=None,
    dry_run: bool = False,
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
    search_labels = tuple(profile.get("search_labels") or ())
    compose_labels = tuple(profile.get("compose_labels") or ())

    if goal_satisfied:
        sat = goal_satisfied(instruction, ui_tree, package)
        if sat:
            return _fp(
                {
                    "action": "done",
                    "reason": sat,
                    "planner": planner,
                    "llm_provider": None,
                },
                "done_goal",
            )

    if "isn't responding" in tl or "not responding" in tl:
        return _fp(
            {
                "action": "tap",
                "x": 540,
                "y": 1395,
                "reason": f"Dismiss ANR Wait ({planner})",
                "planner": planner,
                "llm_provider": None,
            },
            "dismiss_anr",
        )

    opened = (
        f"opened {open_l}" in hist
        or f"open_app({open_l})" in hist
        or f"open_app({app_key})" in hist
        or (f"open_ok" in hist and (open_l in hist or app_key in hist))
        or fg
    )
    if not opened:
        return _fp(
            {
                "action": "open_app",
                "app": open_label,
                "reason": f"Open {open_label} ({planner})",
                "planner": planner,
                "llm_provider": None,
            },
            "open_app",
        )

    typed_contact = _hist_has_type(history, contact)
    tapped_contact = any(
        (
            "tap matching contact" in str(h).lower()
            or "tap contact" in str(h).lower()
            or "select contact" in str(h).lower()
            or "open chat" in str(h).lower()
            or "first search result" in str(h).lower()
        )
        for h in history[-16:]
    )
    # Do NOT treat a tap whose reason was only the name in search field as success
    chat_ok = chat_screen_verified(ui_tree, contact, compose_labels)
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
        "tap send" in str(h).lower()
        or "ime_send" in str(h).lower()
        or "ime_action" in str(h).lower()
        or f"send ({planner}" in str(h).lower()
        for h in history[-16:]
    )
    focused_compose = any(
        "compose" in str(h).lower() or "message field" in str(h).lower()
        for h in history[-16:]
    )
    tried_new_chat = any("new chat" in str(h).lower() for h in history[-16:])
    contact_tap_attempts = sum(
        1
        for h in history[-16:]
        if "matching contact" in str(h).lower()
        or "first search result" in str(h).lower()
    )

    # Sparse tree after search → ask planner/vision (signal via None + caller)
    # We still return wait-style re-eval by swiping minimally or no-op wait tap.
    sparse_after_search = typed_contact and tree_is_sparse(ui_tree)

    # 0) Enter DMs / inbox when still on feed/home (Instagram / dating)
    needs_inbox = bool(profile.get("inbox_labels")) and app_key != "whatsapp"
    if needs_inbox and not tapped_inbox and not typed_contact and not tapped_search:
        if not _tree_node_center(ui_tree, *search_labels):
            c = _tree_node_center(ui_tree, *tuple(profile["inbox_labels"]))
            if c:
                return _fp(
                    {
                        "action": "tap",
                        "x": c[0],
                        "y": c[1],
                        "reason": f"Open inbox/DMs ({planner})",
                        "planner": planner,
                        "llm_provider": None,
                    },
                    "open_inbox",
                )
            if app_key in ("tinder", "bumble", "hinge", "instagram"):
                return _fp(
                    {
                        "action": "tap",
                        "x": 860 if app_key == "instagram" else 900,
                        "y": 150 if app_key == "instagram" else 2280,
                        "reason": f"Open inbox coords fallback ({planner})",
                        "planner": planner,
                        "llm_provider": None,
                    },
                    "open_inbox_fallback",
                )

    # 1) Search — prefer resource-id (deterministic), never vision
    if not typed_contact and not tapped_search:
        search_ids = tuple(profile.get("search_ids") or ())
        c = _tree_id_center(ui_tree, *search_ids) if search_ids else None
        if c is None:
            c = _tree_node_center(ui_tree, *search_labels)
        if c:
            return _fp(
                {
                    "action": "tap",
                    "x": c[0],
                    "y": c[1],
                    "reason": f"Tap Search id/label ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "tap_search",
            )
        fx, fy = profile["search_fallback"]
        return _fp(
            {
                "action": "tap",
                "x": fx,
                "y": fy,
                "reason": f"Tap Search coords fallback ({planner})",
                "planner": planner,
                "llm_provider": None,
            },
            "tap_search_fallback",
        )

    # 2) Type contact into search
    if (tapped_search or _tree_editable_center(ui_tree)) and not typed_contact:
        return _fp(
            {
                "action": "type",
                "text": contact,
                "reason": f"Type contact '{contact}' ({planner})",
                "planner": planner,
                "llm_provider": None,
                "clear": True,
            },
            "type_contact",
        )

    # 3) Tap matching result / open chat (EXCLUDE search EditText)
    if typed_contact and not chat_ok and not typed_message:
        if sparse_after_search:
            # Signal vision by returning None would skip heuristic; instead wait
            # one tick with a no-op that forces re-dump — use tiny wait via back? No.
            # Prefer first-result fallback lower on screen after a short scroll.
            pass
        c = find_contact_result_center(ui_tree, contact, search_labels=search_labels)
        if c:
            return _fp(
                {
                    "action": "tap",
                    "x": c[0],
                    "y": c[1],
                    "reason": f"Tap matching contact '{contact}' ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "tap_contact",
            )
        # Thin tree after typing contact → let vision pick the result row
        if sparse_after_search and contact_tap_attempts == 0:
            return None
        # Alternate route: New chat → search contacts
        if contact_tap_attempts >= 2 and not tried_new_chat:
            nc = _tree_node_center(
                ui_tree, *tuple(profile.get("new_chat_labels") or ())
            )
            if nc:
                return _fp(
                    {
                        "action": "tap",
                        "x": nc[0],
                        "y": nc[1],
                        "reason": f"Alternate route: New chat ({planner})",
                        "planner": planner,
                        "llm_provider": None,
                    },
                    "alt_new_chat",
                )
            # WhatsApp new-chat FAB typical
            return _fp(
                {
                    "action": "tap",
                    "x": 980,
                    "y": 2100,
                    "reason": f"Alternate route: New chat FAB ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "alt_new_chat_fab",
            )
        if hist.count("swipe") < 2:
            return _fp(
                {
                    "action": "swipe",
                    "x1": 540,
                    "y1": 1600,
                    "x2": 540,
                    "y2": 800,
                    "reason": f"Scroll contact results ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "scroll_results",
            )
        # Last resort: tap below search bar (first row), never the search field itself
        return _fp(
            {
                "action": "tap",
                "x": 540,
                "y": 420,
                "reason": f"Tap first search result for '{contact}' ({planner})",
                "planner": planner,
                "llm_provider": None,
            },
            "tap_first_result",
        )

    # 3b) Tapped but chat not verified → retry / alternate (do NOT type message)
    if typed_contact and tapped_contact and not chat_ok and not typed_message:
        if contact_tap_attempts < 4:
            c = find_contact_result_center(
                ui_tree, contact, search_labels=search_labels
            )
            if c:
                return _fp(
                    {
                        "action": "tap",
                        "x": c[0],
                        "y": c[1],
                        "reason": (
                            f"Retry tap contact '{contact}' — chat not verified ({planner})"
                        ),
                        "planner": planner,
                        "llm_provider": None,
                    },
                    "retry_tap_contact",
                )
        if not tried_new_chat:
            return _fp(
                {
                    "action": "tap",
                    "x": 980,
                    "y": 2100,
                    "reason": f"Chat verify failed — try New chat ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "verify_fail_new_chat",
            )
        return _fp(
            {
                "action": "fail",
                "reason": (
                    f"Could not open chat with '{contact}' — "
                    "header/compose not verified after contact taps"
                ),
                "planner": planner,
                "llm_provider": None,
            },
            "verify_fail",
        )

    # 4) Focus compose — only when chat verified
    if chat_ok and not typed_message and not focused_compose:
        compose_ids = tuple(profile.get("compose_ids") or ())
        c = find_compose_center(
            ui_tree, compose_labels, compose_ids, search_labels=search_labels
        )
        if c:
            return _fp(
                {
                    "action": "tap",
                    "x": c[0],
                    "y": c[1],
                    "reason": (f"Focus compose Message/entry field ({planner})"),
                    "planner": planner,
                    "llm_provider": None,
                },
                "focus_compose",
            )
        # No entry/Message in tree (common on Secure Folder / sparse dumps) —
        # defer to vision rather than blind coords that miss the box.
        if tree_is_sparse(ui_tree) or not compose_field_present(
            ui_tree, compose_labels
        ):
            return None
        cx, cy = profile["compose_fallback"]
        return _fp(
            {
                "action": "tap",
                "x": cx,
                "y": cy,
                "reason": f"Focus compose coords fallback ({planner})",
                "planner": planner,
                "llm_provider": None,
            },
            "focus_compose_fallback",
        )

    # 5) Type message — ONLY if chat verified AND target is compose (not search)
    if chat_ok and not typed_message:
        if not focused_is_compose_not_search(ui_tree, compose_labels, search_labels):
            return _fp(
                {
                    "action": "tap",
                    "x": profile["compose_fallback"][0],
                    "y": profile["compose_fallback"][1],
                    "reason": (
                        f"Refuse type — focus looks like search; retarget compose ({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                },
                "refuse_type_search",
            )
        return _fp(
            {
                "action": "type",
                "text": message,
                "reason": f"Type message '{message}' ({planner})",
                "planner": planner,
                "llm_provider": None,
            },
            "type_message",
        )

    # 6) Send — IME_ACTION_SEND first; else tap send id. Dry-run stops here.
    if typed_message and not tapped_send:
        if dry_run:
            return _fp(
                {
                    "action": "done",
                    "reason": (
                        f"dry_run — compose filled with '{message}' "
                        f"for {contact}; send skipped"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                    "dry_run": True,
                    "screenshot": True,
                },
                "dry_run_stop",
            )
        # Prefer our keyboard's performEditorAction(SEND)
        if "ime_send" not in hist and "ime_action" not in hist:
            return _fp(
                {
                    "action": "ime_send",
                    "reason": f"IME_ACTION_SEND via Mobilerun Keyboard ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "ime_send",
            )
        send_ids = tuple(profile.get("send_ids") or ())
        c = find_send_center(ui_tree, tuple(profile["send_labels"]), send_ids=send_ids)
        sx, sy = profile["send_fallback"]
        x, y = c if c else (sx, sy)
        return _fp(
            {
                "action": "tap",
                "x": x,
                "y": y,
                "reason": f"Tap Send id/send ({planner})",
                "planner": planner,
                "llm_provider": None,
            },
            "tap_send",
        )

    # 7) Verify outgoing bubble / re-send
    if tapped_send:
        if outgoing_bubble_present(ui_tree, message):
            return _fp(
                {
                    "action": "done",
                    "reason": (
                        f"Outgoing bubble confirmed for '{message}' "
                        f"to {contact} ({planner})"
                    ),
                    "planner": planner,
                    "llm_provider": None,
                    "outgoing_confirmed": True,
                },
                "done_outgoing_bubble",
            )
        if goal_satisfied:
            sat2 = goal_satisfied(instruction, ui_tree, package)
            if sat2:
                return _fp(
                    {
                        "action": "done",
                        "reason": sat2,
                        "planner": planner,
                        "llm_provider": None,
                    },
                    "done_after_send",
                )
        if hist.count("tap send") + hist.count("re-tap send") + hist.count(
            "ime_send"
        ) < 3:
            c = _tree_node_center(ui_tree, *tuple(profile["send_labels"]))
            sx, sy = profile["send_fallback"]
            x, y = c if c else (sx, sy)
            return _fp(
                {
                    "action": "tap",
                    "x": x,
                    "y": y,
                    "reason": f"Re-tap Send ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "retap_send",
            )

    if fg:
        if chat_ok and not typed_message:
            ec_nodes = [
                n
                for n in _parse_compact_nodes(ui_tree)
                if n.get("editable") and not _is_searchish_node(n, search_labels)
            ]
            if ec_nodes:
                n = ec_nodes[0]
                return _fp(
                    {
                        "action": "tap",
                        "x": n["x"],
                        "y": n["y"],
                        "reason": f"Continue compose ({planner})",
                        "planner": planner,
                        "llm_provider": None,
                    },
                    "continue_compose",
                )
        c = _tree_node_center(ui_tree, *search_labels)
        if c and not typed_contact:
            return _fp(
                {
                    "action": "tap",
                    "x": c[0],
                    "y": c[1],
                    "reason": f"Retry Search ({planner})",
                    "planner": planner,
                    "llm_provider": None,
                },
                "retry_search",
            )
    return None
