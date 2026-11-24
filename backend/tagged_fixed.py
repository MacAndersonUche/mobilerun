"""r45: Tagged fixed runs — auto swipe or auto message. No LLM, never paid.

Mac (24 Nov, spoken): "for auto message click into a profile, send a message, click
the send arrow, then go back into the profile, match by clicking the middle,
then swipe".
Video (24 Nov 2026) supersedes it: tap the deck chat bubble → chat → type →
send arrow → back to the deck. The profile path stays as the fallback when
the deck has no chat bubble.

Real-device map (S21+ 1080x2400, 22 Nov, dm_heuristics DM_APP_PROFILES
["tagged"]): Match game tab ``tab_match_game`` (540, 2200); card buttons
``dislikeBtn`` (220, 1908) · ``chatBtn`` (540, 1911) · ``likeBtn`` (860,
1908); name ``tvUsername``. Never: Go Live FAB, credits, boosts, VIP, gifts,
premium.

Instructions (dating_run): ``fixed tagged swipe N`` / ``fixed tagged message N``.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

try:
    from dm_heuristics import (
        _fp,
        _parse_compact_nodes,
        _tree_id_center,
        tagged_dismiss_exit_dialog,
        tagged_location_overlay_continue,
    )
except ImportError:  # pragma: no cover
    from backend.dm_heuristics import (  # type: ignore
        _fp,
        _parse_compact_nodes,
        _tree_id_center,
        tagged_dismiss_exit_dialog,
        tagged_location_overlay_continue,
    )

PLANNER = "tagged_fixed"
PKG = "com.taggedapp"
MATCH_TAB_XY = (540, 2200)
LIKE_XY = (860, 1908)
CHAT_XY = (540, 1911)
CARD_XY = (540, 900)
MESSAGE_BANK = ("hey how are you", "hi miss", "hello miss", "good morning")
MAX_RECOVER = 10

_INST_RE = re.compile(r"\bfixed\s+tagged\s+(swipe|message)\s+(\d+)", re.I)
_PAID = (
    "credits", "credit", "boost", "vip", "gift", "premium", "subscribe",
    "super like", "superlike", "go live", "buy", "gold", "unlock", "upgrade",
)
_DISMISS = ("close", "not now", "no thanks", "no, thanks", "maybe later", "later",
            "skip", "cancel", "x", "×")


def parse_tagged_instruction(instruction: str) -> Optional[Tuple[str, int]]:
    m = _INST_RE.search(instruction or "")
    if not m:
        return None
    return m.group(1).lower(), max(1, int(m.group(2)))


def _nodes(tree: str) -> List[Dict[str, Any]]:
    return _parse_compact_nodes(tree or "")


def _lab(n: Dict[str, Any]) -> str:
    return str(n.get("label") or n.get("text") or n.get("desc") or "").strip()


def _paid_label(lab: str) -> bool:
    low = lab.lower()
    return any(re.search(rf"\b{re.escape(p)}\b", low) for p in _PAID)


def _paid_screen(tree: str) -> bool:
    """A paid sheet in front (not just a paid chip somewhere on the card)."""
    labs = " ".join(_lab(n) for n in _nodes(tree)).lower()
    return any(
        p in labs
        for p in (
            "buy credits", "get credits", "not enough credits", "go vip",
            "tagged vip", "tagged premium", "upgrade to", "boost your profile",
            "subscribe now",
        )
    )


def _dismiss_xy(tree: str) -> Optional[Tuple[int, int]]:
    for n in _nodes(tree):
        lab = _lab(n).lower()
        nid = str(n.get("id") or "").lower()
        if lab in _DISMISS or nid.endswith(("close", "close_button", "btnclose")):
            if int(n.get("y") or 0) < 2100 and int(n.get("x") or 0) > 0:
                return int(n["x"]), int(n["y"])
    return None


def on_deck(tree: str) -> bool:
    return bool(_tree_id_center(tree, "likeBtn", "id/likeBtn", "id/tagged_like"))


def on_thread(tree: str) -> bool:
    for n in _nodes(tree):
        if n.get("editable"):
            hint = (str(n.get("hint") or "") + " " + _lab(n)).lower()
            if "message" in hint or "type" in hint or "say" in hint or not hint.strip():
                return True
    return bool(_tree_id_center(tree, "id/message_input", "message_input"))


def _bottom_nav(tree: str) -> bool:
    return bool(_tree_id_center(tree, "tab_match_game", "tab_nearby", "tab_chats"))


def _composer(tree: str) -> Tuple[Optional[Tuple[int, int]], str]:
    for n in _nodes(tree):
        if n.get("editable") or "message_input" in str(n.get("id") or ""):
            return (int(n["x"]), int(n["y"])), str(n.get("text") or "").strip()
    return None, ""


def _send_xy(tree: str) -> Optional[Tuple[int, int]]:
    c = _tree_id_center(tree, "id/send_button", "send_button", "btnSend", "sendButton")
    if c:
        return int(c[0]), int(c[1])
    comp, _ = _composer(tree)
    best = None
    for n in _nodes(tree):
        lab = _lab(n).lower()
        if lab in ("send", "send message") and n.get("clickable"):
            return int(n["x"]), int(n["y"])
        # unlabeled clickable just right of the composer = send arrow
        if comp and n.get("clickable") and not lab and not n.get("editable"):
            x, y = int(n.get("x") or 0), int(n.get("y") or 0)
            if x > comp[0] + 200 and abs(y - comp[1]) < 90:
                best = best or (x, y)
    return best


def _deck_chat_xy(tree: str) -> Optional[Tuple[int, int]]:
    """The middle chat-bubble button on the Match deck, else None.

    Video (24 Nov 2026): tapping it opens the chat directly — no need to
    open the profile first. The profile path stays as the fallback when
    the deck has no chat bubble.
    """
    c = _tree_id_center(tree, "chatBtn", "id/chatBtn")
    return (int(c[0]), int(c[1])) if c else None


def _profile_message_xy(tree: str) -> Optional[Tuple[int, int]]:
    """Free message button on an open profile (Message / Chat / chatBtn)."""
    c = _tree_id_center(tree, "chatBtn", "id/chatBtn", "btnMessage", "btn_message",
                        "messageButton", "id/message_button")
    if c:
        return int(c[0]), int(c[1])
    for n in _nodes(tree):
        lab = _lab(n).lower()
        if n.get("clickable") and lab in ("message", "chat", "send message", "send a message"):
            if not _paid_label(lab):
                return int(n["x"]), int(n["y"])
    return None


def _middle_like_xy(tree: str) -> Optional[Tuple[int, int]]:
    """The free match/like button: ``likeBtn``, else a Like/Match/heart near
    the middle of the bottom row. Never chat, pass or anything paid."""
    c = _tree_id_center(tree, "likeBtn", "id/likeBtn", "id/tagged_like", "btnLike",
                        "matchButton", "id/match_button")
    if c:
        return int(c[0]), int(c[1])
    best = None
    for n in _nodes(tree):
        lab = _lab(n).lower()
        if not n.get("clickable") or _paid_label(lab):
            continue
        if lab in ("like", "match", "yes", "heart", "like profile"):
            x, y = int(n.get("x") or 0), int(n.get("y") or 0)
            score = abs(x - 540)
            if best is None or score < best[0]:
                best = (score, x, y)
    return (best[1], best[2]) if best else None


def _card_name(tree: str) -> str:
    for n in _nodes(tree):
        if "tvusername" in str(n.get("id") or "").lower():
            return _lab(n)
    return ""


def _act(kind: str, step: str, reason: str, dry_run: bool, **kw: Any) -> Dict[str, Any]:
    a = {
        "action": kind,
        "reason": f"{reason} ({PLANNER})",
        "planner": PLANNER,
        "llm_provider": None,
        "dry_run": bool(dry_run),
        "_no_llm_handoff": True,
    }
    a.update(kw)
    return _fp(a, step)


def plan_tagged_fixed(
    instruction: str,
    ui_tree: str,
    history: Optional[List[str]] = None,
    *,
    state: Optional[Dict[str, Any]] = None,
    dry_run: bool = False,
    message: str = "",
) -> Optional[Dict[str, Any]]:
    parsed = parse_tagged_instruction(instruction)
    if not parsed:
        return None
    mode, target = parsed
    st = state if isinstance(state, dict) else {}
    tg = st.setdefault("tagged_fixed", {"done": 0, "phase": "deck", "recover": 0})
    st["tagged_fixed"] = tg
    done = int(tg.get("done") or 0)
    text = (message or "").strip() or MESSAGE_BANK[0]
    unit = "messages" if mode == "message" else "likes"

    if done >= target:
        return _act("done", "tagged_fixed_done",
                    f"Tagged {mode} finished {done}/{target} {unit}", dry_run)

    # Harmless system / app popups first
    for helper in (tagged_dismiss_exit_dialog, tagged_location_overlay_continue):
        a = helper(ui_tree, planner=PLANNER)
        if a:
            a["_no_llm_handoff"] = True
            return a

    pkgs = re.search(r'packages="([^"]*)"', ui_tree or "")
    if not (ui_tree or "").strip() or (pkgs and PKG not in pkgs.group(1)):
        tg["recover"] = int(tg.get("recover") or 0) + 1
        if tg["recover"] > MAX_RECOVER:
            return _act("fail", "tagged_fixed_lost", "Tagged never came up — stop", dry_run)
        return _act("open_app", "tagged_fixed_open", "Open Tagged", dry_run,
                    app="Tagged", package=PKG)

    if _paid_screen(ui_tree):
        xy = _dismiss_xy(ui_tree)
        n = int(tg.get("paid_dismiss") or 0) + 1
        tg["paid_dismiss"] = n
        if n > 3:
            return _act("fail", "tagged_fixed_paid_stop",
                        "Tagged paid screen will not close — stop, nothing bought", dry_run)
        if xy:
            return _act("tap", "tagged_fixed_paid_close",
                        "Close Tagged paid popup — nothing bought", dry_run, x=xy[0], y=xy[1])
        return _act("press_button", "tagged_fixed_paid_back",
                    "Tagged paid popup — Back, nothing bought", dry_run, button="back")

    phase = str(tg.get("phase") or "deck")

    # ---------------- auto swipe: free like on the match game ----------
    if mode == "swipe":
        if on_deck(ui_tree):
            tg["recover"] = 0
            if tg.get("awaiting_like"):
                tg["awaiting_like"] = False
                done += 1
                tg["done"] = done
                if done >= target:
                    return _act("done", "tagged_fixed_done",
                                f"Tagged swipe finished {done}/{target} likes", dry_run)
            if dry_run:
                return _act("done", "tagged_fixed_dry", f"[DRY RUN] on Tagged match game; would like "
                            f"{target} — no tap", True, dry_run_verified=True)
            xy = _middle_like_xy(ui_tree) or LIKE_XY
            tg["awaiting_like"] = True
            return _act("tap", "tagged_fixed_like",
                        f"Tagged free like {done + 1}/{target} ({_card_name(ui_tree) or 'card'})",
                        dry_run, x=xy[0], y=xy[1])
        return _recover(ui_tree, tg, dry_run)

    # ---------------- auto message --------------------------------------
    pending = str(tg.get("awaiting_sent") or "")
    if pending:
        comp, box = _composer(ui_tree)
        if comp and box.lower() == pending.lower():
            if int(tg.get("send_retry") or 0) < 1:
                tg["send_retry"] = 1
                xy = _send_xy(ui_tree)
                if xy:
                    return _act("tap", "tagged_fixed_send_retry",
                                f"Tagged Send again — '{pending}' still in the box", dry_run,
                                x=xy[0], y=xy[1])
            return _act("fail", "tagged_fixed_not_sent",
                        f"Tagged message did not send ('{pending}' still in the box) — stop",
                        dry_run)
        tg["awaiting_sent"] = ""
        tg["send_retry"] = 0
        tg["sent_this"] = True
        tg["phase"] = "back_to_deck"
        phase = "back_to_deck"

    if phase == "deck":
        if on_deck(ui_tree):
            tg["recover"] = 0
            tg["name"] = _card_name(ui_tree)
            if dry_run:
                return _act("done", "tagged_fixed_dry",
                            f"[DRY RUN] on Tagged match game; would tap the chat bubble, send "
                            f"'{text}', then back to the deck — no tap", True,
                            dry_run_verified=True, would_send_text=text)
            # Video (24 Nov 2026): tap the deck chat bubble straight into
            # the chat. The profile path below is the fallback when the
            # deck has no chat bubble.
            chat = _deck_chat_xy(ui_tree)
            if chat:
                tg["phase"] = "compose"
                return _act("tap", "tagged_fixed_open_chat",
                            f"Open the chat on {tg.get('name') or 'this'} card "
                            f"(deck chat bubble)", dry_run,
                            x=chat[0], y=chat[1])
            tg["phase"] = "profile"
            name_xy = _tree_id_center(ui_tree, "tvUsername", "id/tvUsername")
            xy = (int(name_xy[0]), int(name_xy[1])) if name_xy else CARD_XY
            return _act("tap", "tagged_fixed_open_profile",
                        f"Open {tg.get('name') or 'this'} profile on Tagged", dry_run,
                        x=xy[0], y=xy[1])
        return _recover(ui_tree, tg, dry_run)

    if phase == "profile":
        if on_thread(ui_tree):
            tg["phase"] = "compose"
            phase = "compose"
        else:
            xy = _profile_message_xy(ui_tree)
            tg["profile_tries"] = int(tg.get("profile_tries") or 0) + 1
            if xy and tg["profile_tries"] <= 3:
                return _act("tap", "tagged_fixed_open_message",
                            "Open the free message box on this Tagged profile", dry_run,
                            x=xy[0], y=xy[1])
            if tg["profile_tries"] > 3:
                tg["profile_tries"] = 0
                tg["phase"] = "deck"
                return _act("press_button", "tagged_fixed_no_message",
                            "No free message button on this profile — back to the match game",
                            dry_run, button="back")
            return _act("wait", "tagged_fixed_profile_wait",
                        "Waiting for the Tagged profile to load", dry_run, seconds=1.5)

    if phase == "compose":
        comp, box = _composer(ui_tree)
        if not comp:
            tg["phase"] = "profile"
            return _act("wait", "tagged_fixed_compose_wait",
                        "Waiting for the Tagged message box", dry_run, seconds=1.0)
        if box.lower() != text.lower():
            return _act("type", "tagged_fixed_type", f"Type Tagged message '{text}'",
                        dry_run, text=text, clear=True, x=comp[0], y=comp[1])
        xy = _send_xy(ui_tree)
        if not xy:
            return _act("fail", "tagged_fixed_no_send",
                        "Tagged send arrow not found — stop, nothing sent", dry_run)
        tg["awaiting_sent"] = text
        return _act("tap", "tagged_fixed_send",
                    f"Tagged send arrow — message {done + 1}/{target}", dry_run,
                    x=xy[0], y=xy[1])

    if phase == "back_to_deck":
        # Video (24 Nov 2026): after the send, go straight back to the
        # deck — no profile, no middle-match tap.
        if on_thread(ui_tree):
            return _act("press_button", "tagged_fixed_thread_back",
                        "Message sent — Back to the match game", dry_run, button="back")
        if tg.get("sent_this"):
            tg["sent_this"] = False
            done += 1
            tg["done"] = done
        tg["phase"] = "after_match"
        phase = "after_match"

    if phase == "after_match":
        tg["phase"] = "deck"
        if done >= target:
            return _act("done", "tagged_fixed_done",
                        f"Tagged message finished {done}/{target} messages", dry_run)
        if on_deck(ui_tree):
            if _card_name(ui_tree) and _card_name(ui_tree) == tg.get("name"):
                # still the same person → swipe on (free like) to the next one
                xy = _middle_like_xy(ui_tree) or LIKE_XY
                return _act("tap", "tagged_fixed_next",
                            "Swipe on to the next person (free like)", dry_run,
                            x=xy[0], y=xy[1])
            return plan_tagged_fixed(instruction, ui_tree, history, state=st,
                                     dry_run=dry_run, message=message)
        if not _bottom_nav(ui_tree):
            return _act("press_button", "tagged_fixed_after_back",
                        "Back to the match game for the next person", dry_run, button="back")
        return _recover(ui_tree, tg, dry_run)

    tg["phase"] = "deck"
    return _recover(ui_tree, tg, dry_run)


def _recover(tree: str, tg: Dict[str, Any], dry_run: bool) -> Dict[str, Any]:
    """Back toward the Match game: tab when the bottom bar shows (never Back
    off the top screen), Back inside chats / profiles. Capped, no AI."""
    n = int(tg.get("recover") or 0) + 1
    tg["recover"] = n
    if n > MAX_RECOVER:
        return _act("fail", "tagged_fixed_recover_fail",
                    f"Tagged: could not get back to the match game after {MAX_RECOVER} tries",
                    dry_run)
    if _bottom_nav(tree):
        c = _tree_id_center(tree, "tab_match_game", "id/tab_match_game")
        xy = (int(c[0]), int(c[1])) if c else MATCH_TAB_XY
        return _act("tap", "tagged_fixed_tab", "Tap Tagged Match game tab", dry_run,
                    x=xy[0], y=xy[1])
    if n % 3 == 0:
        return _act("tap", "tagged_fixed_tab_xy", "Tap Tagged Match game tab (map)", dry_run,
                    x=MATCH_TAB_XY[0], y=MATCH_TAB_XY[1])
    return _act("press_button", "tagged_fixed_back", "Back toward the Tagged match game",
                dry_run, button="back")
