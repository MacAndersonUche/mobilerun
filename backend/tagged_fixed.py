"""r45: Tagged fixed runs — auto swipe or auto message. No LLM, never paid.

Mac (24 Nov, spoken): "for auto message click into a profile, send a message, click
the send arrow, then go back into the profile, match by clicking the middle,
then swipe".
Video (27 Nov 2026, Mac) is the required path: tap the centre of the photo
on the Match deck → "Your message" at the bottom → type a bank line →
blue square send arrow → Android Back to the deck → green heart (likeBtn)
to like and advance. Never a bare like, never the chats tab, never paid
(credits, boosts, VIP, gold, gifts, Go Live).

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
MESSAGE_BANK = (
    "hey how are you",
    "hi miss",
    "hello miss",
    "good morning",
    "good evening beautiful",
)
MAX_RECOVER = 10

_INST_RE = re.compile(r"\bfixed\s+tagged\s+(swipe|message)\s+(\d+)", re.I)
_PAID = (
    "credits",
    "credit",
    "boost",
    "vip",
    "gift",
    "premium",
    "subscribe",
    "super like",
    "superlike",
    "go live",
    "buy",
    "gold",
    "unlock",
    "upgrade",
)
_DISMISS = (
    "close",
    "not now",
    "no thanks",
    "no, thanks",
    "maybe later",
    "later",
    "skip",
    "cancel",
    "x",
    "×",
)


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
            "buy credits",
            "get credits",
            "not enough credits",
            "go vip",
            "tagged vip",
            "tagged premium",
            "upgrade to",
            "boost your profile",
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
    c = _tree_id_center(
        tree,
        "imSendMessageButton",
        "id/imSendMessageButton",
        "id/send_button",
        "send_button",
        "btnSend",
        "sendButton",
        "send_message_button",
    )
    if c and int(c[1]) < 2000:
        return int(c[0]), int(c[1])
    # y≥2000 means the IME is closed and the bar sits on the bottom
    # nav (27 Nov: send was planned at (991, 2187) and hit My likes).
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
    if best:
        return best
    # 27 Nov S21+: imSendMessageButton is an ImageView often not marked
    # clickable, so compact dumps omit it. Sit just right of the box
    # (composer x2=922 → send centre 995 on the live leidy tree).
    if comp:
        ex2 = None
        cy = int(comp[1])
        for n in _nodes(tree):
            if (
                n.get("editable")
                or "etmessageedittext" in str(n.get("id") or "").lower()
            ):
                if n.get("x2") is not None:
                    ex2 = int(n["x2"])
                    cy = int(n["y"])
        if cy >= 2000:
            # Keyboard is closed; the bar sits on the bottom nav.
            # Caller should focus the composer first (y≈1323 with IME up).
            return None
        if ex2:
            return (min(ex2 + 73, 1040), cy)
        return (995, cy)
    return None


def _photo_xy(tree: str) -> Tuple[int, int]:
    """Centre of the Match-deck photo, never a card button or the nav.

    Mac (27 Nov video): tap the photo to open the profile, not the chat
    bubble and not the green heart. Fallback CARD_XY (540, 900) is the
    mid-photo point on the S21+ 1080x2400 map.
    """
    banned_ids = (
        "likebtn",
        "dislikebtn",
        "chatbtn",
        "tab_",
        "fab",
        "credits",
        "boost",
        "vip",
        "gift",
        "golive",
        "go_live",
        "tvusername",
    )
    best = None
    best_area = 0
    for n in _nodes(tree):
        nid = str(n.get("id") or "").lower()
        if any(b in nid for b in banned_ids):
            continue
        if _paid_label(_lab(n)):
            continue
        x1, y1, x2, y2 = n.get("x1"), n.get("y1"), n.get("x2"), n.get("y2")
        if None in (x1, y1, x2, y2):
            continue
        w, h = int(x2) - int(x1), int(y2) - int(y1)
        if w < 400 or h < 400:
            continue
        cy = (int(y1) + int(y2)) // 2
        if cy < 200 or cy > 1800:
            continue
        area = w * h
        if area > best_area:
            best_area = area
            best = ((int(x1) + int(x2)) // 2, cy)
    return best or CARD_XY


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
    c = _tree_id_center(
        tree,
        "chatBtn",
        "id/chatBtn",
        "btnMessage",
        "btn_message",
        "messageButton",
        "id/message_button",
    )
    if c:
        return int(c[0]), int(c[1])
    for n in _nodes(tree):
        lab = _lab(n).lower()
        if n.get("clickable") and lab in (
            "message",
            "chat",
            "send message",
            "send a message",
        ):
            if not _paid_label(lab):
                return int(n["x"]), int(n["y"])
    return None


def _middle_like_xy(tree: str) -> Optional[Tuple[int, int]]:
    """The free match/like button: ``likeBtn``, else a Like/Match/heart near
    the middle of the bottom row. Never chat, pass or anything paid."""
    c = _tree_id_center(
        tree,
        "likeBtn",
        "id/likeBtn",
        "id/tagged_like",
        "btnLike",
        "matchButton",
        "id/match_button",
    )
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
            lab = _lab(n).split(",")[0].strip()
            if lab:
                return lab
    try:
        from dm_heuristics import tagged_deck_card_name as _deck_name
    except ImportError:  # pragma: no cover
        from backend.dm_heuristics import tagged_deck_card_name as _deck_name  # type: ignore
    return (_deck_name(tree) or "").split(",")[0].strip()


def _thread_name(tree: str) -> str:
    for n in _nodes(tree):
        if str(n.get("id") or "").lower().endswith("username") or str(
            n.get("id") or ""
        ).lower().endswith("/username"):
            lab = _lab(n).split(",")[0].strip()
            if lab:
                return lab
    return ""


def _norm_name(name: str) -> str:
    import unicodedata

    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.strip().lower().split())


def _is_ours(lab: str, our_text: str) -> bool:
    a, b = (lab or "").strip().lower(), (our_text or "").strip().lower()
    if not a or not b:
        return False
    return a == b or a.startswith(b) or b.startswith(a)


def sent_bubble(tree: str, text: str) -> bool:
    """A non-editable chat bubble carrying our line (not the composer)."""
    want = (text or "").strip()
    if not want:
        return False
    for n in _nodes(tree):
        if n.get("editable"):
            continue
        nid = str(n.get("id") or "").lower()
        if "etmessageedittext" in nid or "message_input" in nid:
            continue
        lab = _lab(n).strip()
        if not lab:
            continue
        low = lab.lower()
        if low in ("your message", "say hello") or "make the first move" in low:
            continue
        is_bubble = any(
            s in nid
            for s in (
                "tvmessagetext",
                "cloutermessageitem",
                "prlmessageitem",
                "flmessagecontainer",
                "tvmessage",
            )
        )
        if is_bubble or (not nid and int(n.get("y") or 0) < 1800):
            if _is_ours(lab, want):
                return True
    return False


def on_existing_thread(tree: str, our_text: str = "") -> bool:
    """Prior messages from before this send — not a first-move screen,
    and not only our just-sent bank line."""
    blob = " ".join(_lab(n) for n in _nodes(tree)).lower()
    if "make the first move" in blob or (
        "say hello" in blob and "your message" in blob
    ):
        return False
    if any("llemptyview" in str(n.get("id") or "").lower() for n in _nodes(tree)):
        return False
    for n in _nodes(tree):
        nid = str(n.get("id") or "").lower()
        if n.get("editable") or "etmessageedittext" in nid or "message_input" in nid:
            continue
        if any(
            s in nid
            for s in (
                "tvmessagetext",
                "cloutermessageitem",
                "dcbadgedate",
                "prlmessageitem",
            )
        ):
            lab = _lab(n).strip()
            if _is_ours(lab, our_text):
                continue
            if "dcbadgedate" in nid:
                low = lab.lower()
                # "Today" / a clock time appears on a just-sent bubble.
                if not lab or low in ("today", "just now") or ":" in lab:
                    continue
                return True
            if (
                lab.lower() in ("your message", "say hello")
                or "make the first move" in lab.lower()
            ):
                continue
            # Empty wrappers around our just-sent bubble are not prior mail.
            if lab:
                return True
    return False


def _vision_answer(st: Dict[str, Any], tag: str) -> Optional[bool]:
    """YES/NO from the last screenshot check (stored on bulk_message_new)."""
    bulk = (
        st.get("bulk_message_new")
        if isinstance(st.get("bulk_message_new"), dict)
        else {}
    )
    vlast = (
        bulk.get("_vision_last") if isinstance(bulk.get("_vision_last"), dict) else {}
    )
    if vlast.get("tag") != tag:
        return None
    if not str(vlast.get("raw") or "").strip():
        return None
    return bool(vlast.get("ok"))


_SENT_BUBBLE_VISION = (
    "Tagged dating app chat screenshot. Is there a sent chat bubble in the "
    'thread body that contains the exact text "{text}"? If that text is only '
    'in the "Your message" composer at the bottom and no sent bubble is '
    "visible, or this is not a chat thread, answer NO. Reply YES or NO only."
)


def _name_in(tg: Dict[str, Any], key: str, name: str) -> bool:
    want = _norm_name(name)
    if not want:
        return False
    return any(_norm_name(x) == want for x in (tg.get(key) or []) if x)


def _remember_sent(tg: Dict[str, Any], name: str) -> None:
    if not name:
        return
    names = list(tg.get("sent_names") or [])
    if not _name_in(tg, "sent_names", name):
        names.append(name)
        tg["sent_names"] = names


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
        return _act(
            "done",
            "tagged_fixed_done",
            f"Tagged {mode} finished {done}/{target} {unit}",
            dry_run,
        )

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
            return _act(
                "fail", "tagged_fixed_lost", "Tagged never came up — stop", dry_run
            )
        return _act(
            "open_app",
            "tagged_fixed_open",
            "Open Tagged",
            dry_run,
            app="Tagged",
            package=PKG,
        )

    if _paid_screen(ui_tree):
        xy = _dismiss_xy(ui_tree)
        n = int(tg.get("paid_dismiss") or 0) + 1
        tg["paid_dismiss"] = n
        if n > 3:
            return _act(
                "fail",
                "tagged_fixed_paid_stop",
                "Tagged paid screen will not close — stop, nothing bought",
                dry_run,
            )
        if xy:
            return _act(
                "tap",
                "tagged_fixed_paid_close",
                "Close Tagged paid popup — nothing bought",
                dry_run,
                x=xy[0],
                y=xy[1],
            )
        return _act(
            "press_button",
            "tagged_fixed_paid_back",
            "Tagged paid popup — Back, nothing bought",
            dry_run,
            button="back",
        )

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
                    return _act(
                        "done",
                        "tagged_fixed_done",
                        f"Tagged swipe finished {done}/{target} likes",
                        dry_run,
                    )
            if dry_run:
                return _act(
                    "done",
                    "tagged_fixed_dry",
                    f"[DRY RUN] on Tagged match game; would like " f"{target} — no tap",
                    True,
                    dry_run_verified=True,
                )
            xy = _middle_like_xy(ui_tree) or LIKE_XY
            tg["awaiting_like"] = True
            return _act(
                "tap",
                "tagged_fixed_like",
                f"Tagged free like {done + 1}/{target} ({_card_name(ui_tree) or 'card'})",
                dry_run,
                x=xy[0],
                y=xy[1],
            )
        return _recover(ui_tree, tg, dry_run)

    # ---------------- auto message --------------------------------------
    # (a) Count a just-sent bubble BEFORE the existing-chat hook. After
    # a successful send the new bubble used to look like an existing
    # chat, so the job backed out and tapped X instead of counting and
    # tapping the green heart.
    pending = str(tg.get("awaiting_sent") or "")
    if mode == "message" and pending:
        tname = _thread_name(ui_tree)
        if tname:
            tg["name"] = tname
        comp, box = _composer(ui_tree)
        bubble = sent_bubble(ui_tree, pending)
        ans = _vision_answer(st, "tagged_sent_bubble")
        still_in_box = bool(comp and box.lower() == pending.lower())
        confirmed = bool(bubble or ans is True or (not still_in_box))
        if confirmed:
            tg["awaiting_sent"] = ""
            tg["send_retry"] = 0
            tg["confirm_tries"] = 0
            tg["sent_this"] = True
            _remember_sent(tg, str(tg.get("name") or ""))
            tg["phase"] = "back_to_deck"
            phase = "back_to_deck"
            if on_thread(ui_tree):
                act = _act(
                    "press_button",
                    "tagged_fixed_thread_back",
                    f"Message sent to {tg.get('name') or 'them'} — Back to the match game",
                    dry_run,
                    button="back",
                )
                act["_vision_check"] = _SENT_BUBBLE_VISION.format(text=pending)
                act["_vision_tag"] = "tagged_sent_bubble"
                return act
        elif still_in_box and not bubble:
            if int(tg.get("send_retry") or 0) < 1:
                tg["send_retry"] = 1
                xy = _send_xy(ui_tree)
                if xy:
                    return _act(
                        "tap",
                        "tagged_fixed_send_retry",
                        f"Tagged Send again — '{pending}' still in the box",
                        dry_run,
                        x=xy[0],
                        y=xy[1],
                    )
            return _act(
                "fail",
                "tagged_fixed_not_sent",
                f"Tagged message did not send ('{pending}' still in the box) — stop",
                dry_run,
            )
        else:
            if int(tg.get("confirm_tries") or 0) < 2:
                tg["confirm_tries"] = int(tg.get("confirm_tries") or 0) + 1
                return _act(
                    "wait",
                    "tagged_fixed_confirm_sent",
                    "Checking the screenshot for the sent message bubble",
                    dry_run,
                    seconds=1.0,
                    delay_s=1.0,
                    _vision_check=_SENT_BUBBLE_VISION.format(text=pending),
                    _vision_tag="tagged_sent_bubble",
                )
            return _act(
                "fail",
                "tagged_fixed_not_sent",
                "Tagged message send was not confirmed — stop",
                dry_run,
            )

    # Existing conversation, or this line already delivered (27 Nov:
    # photo on Naomi's Match card opened her 22 Nov thread). Never send
    # there. Clear leftover bank text, Back, then X on the deck to skip.
    already = (
        mode == "message"
        and not tg.get("sent_this")
        and str(tg.get("phase") or "") not in ("back_to_deck", "after_match")
    )
    if already:
        tname = _thread_name(ui_tree)
        if tname:
            tg["name"] = tname
        skip_them = bool(
            tname
            and (_name_in(tg, "skip_names", tname) or _name_in(tg, "sent_names", tname))
        )
        if on_thread(ui_tree) and (
            on_existing_thread(ui_tree, text) or sent_bubble(ui_tree, text) or skip_them
        ):
            tg["existing"] = tname or tg.get("name") or "this chat"
            _comp, box = _composer(ui_tree)
            if (box or "").strip() and not tg.get("cleared_existing"):
                tg["cleared_existing"] = True
                tg["phase"] = "skip_existing"
                return _act(
                    "type",
                    "tagged_fixed_clear_existing",
                    f"Clear leftover text in existing chat with {tg['existing']} — will not send",
                    dry_run,
                    text="",
                    clear=True,
                    _clear_only=True,
                )
            tg["phase"] = "skip_existing"
            return _act(
                "press_button",
                "tagged_fixed_existing_back",
                f"Existing chat with {tg['existing']} — Back, will not message them",
                dry_run,
                button="back",
            )

    if mode == "message" and str(tg.get("phase") or "") == "skip_existing":
        if on_thread(ui_tree):
            return _act(
                "press_button",
                "tagged_fixed_existing_back",
                "Still in an existing Tagged chat — Back, will not message them",
                dry_run,
                button="back",
            )
        if on_deck(ui_tree):
            tg["recover"] = 0
            xy = _tree_id_center(ui_tree, "dislikeBtn", "id/dislikeBtn") or (220, 1908)
            tg["phase"] = "deck"
            tg["liked_this"] = False
            tg["cleared_existing"] = False
            return _act(
                "tap",
                "tagged_fixed_skip_existing",
                f"Skip {_card_name(ui_tree) or tg.get('existing') or 'this card'} "
                f"(already a chat) — X, not the green heart",
                dry_run,
                x=int(xy[0]),
                y=int(xy[1]),
            )
        return _recover(ui_tree, tg, dry_run)

    if phase == "deck":
        if on_deck(ui_tree):
            tg["recover"] = 0
            # Name is only a hint here — the opened thread's toolbar
            # name is the source of truth (the Match stack can show
            # several names at once).
            tg["name"] = _card_name(ui_tree)
            if dry_run:
                return _act(
                    "done",
                    "tagged_fixed_dry",
                    f"[DRY RUN] on Tagged match game; would tap the photo, type "
                    f"'{text}' in Your message, send, Back, then the green heart "
                    f"— no tap",
                    True,
                    dry_run_verified=True,
                    would_send_text=text,
                )
            # Video (27 Nov 2026): tap the centre of the photo, then
            # "Your message". Never the chat bubble (that is not the
            # required first-contact path) and never a bare like.
            tg["phase"] = "profile"
            tg["profile_tries"] = 0
            xy = _photo_xy(ui_tree)
            return _act(
                "tap",
                "tagged_fixed_open_profile",
                f"Open {tg.get('name') or 'this'} profile (tap the photo)",
                dry_run,
                x=xy[0],
                y=xy[1],
            )
        return _recover(ui_tree, tg, dry_run)

    if phase == "profile":
        if on_thread(ui_tree):
            tname = _thread_name(ui_tree)
            if tname:
                tg["name"] = tname
            tg["phase"] = "compose"
            phase = "compose"
        else:
            xy = _profile_message_xy(ui_tree)
            tg["profile_tries"] = int(tg.get("profile_tries") or 0) + 1
            if xy and tg["profile_tries"] <= 3:
                return _act(
                    "tap",
                    "tagged_fixed_open_message",
                    "Open the free message box on this Tagged profile",
                    dry_run,
                    x=xy[0],
                    y=xy[1],
                )
            if tg["profile_tries"] > 3:
                tg["profile_tries"] = 0
                tg["phase"] = "deck"
                return _act(
                    "press_button",
                    "tagged_fixed_no_message",
                    "No free message button on this profile — back to the match game",
                    dry_run,
                    button="back",
                )
            return _act(
                "wait",
                "tagged_fixed_profile_wait",
                "Waiting for the Tagged profile to load",
                dry_run,
                seconds=1.5,
            )

    if phase == "compose":
        tname = _thread_name(ui_tree)
        if tname:
            tg["name"] = tname
        comp, box = _composer(ui_tree)
        if not comp:
            tg["phase"] = "profile"
            return _act(
                "wait",
                "tagged_fixed_compose_wait",
                "Waiting for the Tagged message box",
                dry_run,
                seconds=1.0,
            )
        if box.lower() != text.lower():
            return _act(
                "type",
                "tagged_fixed_type",
                f"Type Tagged message '{text}'",
                dry_run,
                text=text,
                clear=True,
                x=comp[0],
                y=comp[1],
            )
        xy = _send_xy(ui_tree)
        if not xy:
            # Keyboard closed: the send arrow sits on the nav (y≈2196
            # on 27 Nov, which is My likes). Focus the box first.
            if int(comp[1]) >= 1800:
                return _act(
                    "tap",
                    "tagged_fixed_focus_composer",
                    "Open the keyboard so the send arrow is above the nav",
                    dry_run,
                    x=comp[0],
                    y=comp[1],
                )
            return _act(
                "fail",
                "tagged_fixed_no_send",
                "Tagged send arrow not found — stop, nothing sent",
                dry_run,
            )
        tg["awaiting_sent"] = text
        return _act(
            "tap",
            "tagged_fixed_send",
            f"Tagged send arrow — message {done + 1}/{target}",
            dry_run,
            x=xy[0],
            y=xy[1],
        )

    if phase == "back_to_deck":
        # Video (27 Nov 2026): after the send, Back to the Match deck, then
        # the green heart (including on the last card).
        if on_thread(ui_tree):
            return _act(
                "press_button",
                "tagged_fixed_thread_back",
                "Message sent — Back to the match game",
                dry_run,
                button="back",
            )
        if tg.get("sent_this"):
            tg["sent_this"] = False
            done += 1
            tg["done"] = done
        tg["phase"] = "after_match"
        phase = "after_match"

    if phase == "after_match":
        if on_thread(ui_tree):
            return _act(
                "press_button",
                "tagged_fixed_thread_back",
                "Message sent — Back to the match game",
                dry_run,
                button="back",
            )
        if on_deck(ui_tree):
            tg["recover"] = 0
            # The stack name often disagrees with the thread we just
            # messaged. After a confirmed send, like the current top
            # card (likeBtn) once — that is Mac's video path.
            if not tg.get("liked_this"):
                xy = _middle_like_xy(ui_tree) or LIKE_XY
                tg["liked_this"] = True
                who = tg.get("name") or _card_name(ui_tree) or "them"
                return _act(
                    "tap",
                    "tagged_fixed_like_after",
                    f"Green heart after the message to {who}",
                    dry_run,
                    x=xy[0],
                    y=xy[1],
                )
            tg["liked_this"] = False
            tg["phase"] = "deck"
            if done >= target:
                return _act(
                    "done",
                    "tagged_fixed_done",
                    f"Tagged message finished {done}/{target} messages",
                    dry_run,
                )
            return plan_tagged_fixed(
                instruction,
                ui_tree,
                history,
                state=st,
                dry_run=dry_run,
                message=message,
            )
        if not _bottom_nav(ui_tree):
            return _act(
                "press_button",
                "tagged_fixed_after_back",
                "Back to the match game for the next person",
                dry_run,
                button="back",
            )
        return _recover(ui_tree, tg, dry_run)

    tg["phase"] = "deck"
    return _recover(ui_tree, tg, dry_run)


def _recover(tree: str, tg: Dict[str, Any], dry_run: bool) -> Dict[str, Any]:
    """Back toward the Match game: tab when the bottom bar shows (never Back
    off the top screen), Back inside chats / profiles. Capped, no AI."""
    n = int(tg.get("recover") or 0) + 1
    tg["recover"] = n
    if n > MAX_RECOVER:
        return _act(
            "fail",
            "tagged_fixed_recover_fail",
            f"Tagged: could not get back to the match game after {MAX_RECOVER} tries",
            dry_run,
        )
    if _bottom_nav(tree):
        c = _tree_id_center(tree, "tab_match_game", "id/tab_match_game")
        xy = (int(c[0]), int(c[1])) if c else MATCH_TAB_XY
        return _act(
            "tap",
            "tagged_fixed_tab",
            "Tap Tagged Match game tab",
            dry_run,
            x=xy[0],
            y=xy[1],
        )
    if n % 3 == 0:
        return _act(
            "tap",
            "tagged_fixed_tab_xy",
            "Tap Tagged Match game tab (map)",
            dry_run,
            x=MATCH_TAB_XY[0],
            y=MATCH_TAB_XY[1],
        )
    return _act(
        "press_button",
        "tagged_fixed_back",
        "Back toward the Tagged match game",
        dry_run,
        button="back",
    )
