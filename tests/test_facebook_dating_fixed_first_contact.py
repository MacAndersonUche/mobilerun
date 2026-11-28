"""Facebook Dating first-contact: photo comment is the like; never Spotlight/Crush."""

from __future__ import annotations

from pathlib import Path

from backend.bulk_bench_heuristics import parse_bulk_goal, plan_bulk_bench
from backend.facebook_dating_fixed_first_contact import (
    DAILY_CAP,
    LIKE_XY,
    PHOTO_COMMENT_TEXT,
    SEND_XY,
    plan_facebook_dating_fixed_first_contact,
)

FIX = Path(__file__).resolve().parent / "fixtures" / "dm"


def test_parse_first_contact_facebook_dating():
    g = parse_bulk_goal("send 2 first contact messages on Facebook Dating")
    assert g is not None
    assert g["kind"] == "message_new"
    assert g["count"] == 2
    assert g["app"] == "facebook"
    assert DAILY_CAP == 50
    assert PHOTO_COMMENT_TEXT == "hi miss you look beautiful"


def test_dry_comment_sheet_uses_mac_text_never_types():
    tree = (FIX / "fb_dating_comment_sheet.xml").read_text(encoding="utf-8")
    # Stick the fixture line — live runs pick from the opener library.
    act = plan_bulk_bench(
        "send 2 first contact messages on Facebook Dating",
        tree,
        ["Opened Facebook Dating", "Tap Facebook Dating profile photo"],
        state={"bulk_message_new": {"done": 0, "text": PHOTO_COMMENT_TEXT}},
        package="com.facebook.katana",
        dry_run=True,
    )
    assert act is not None
    assert act.get("action") == "done"
    assert act.get("dry_run_verified") is True
    assert act.get("would_send_text") == PHOTO_COMMENT_TEXT


def test_live_types_mac_text_then_sends_not_heart():
    tree = (FIX / "fb_dating_comment_sheet.xml").read_text(encoding="utf-8")
    st = {"bulk_message_new": {"done": 0, "typed": False, "text": PHOTO_COMMENT_TEXT}}
    act = plan_facebook_dating_fixed_first_contact(
        "send 2 first contact messages on Facebook Dating",
        tree,
        ["Opened Facebook Dating"],
        state=st,
        dry_run=False,
        message=PHOTO_COMMENT_TEXT,
        target=2,
    )
    assert act is not None
    assert act.get("action") == "type"
    assert act.get("text") == "hi miss you look beautiful"
    # Discover typing is a paste (one commit), never chunked human-paced.
    assert act.get("humanize") is False

    # The same empty box again: the type never landed, so Send must NOT be
    # tapped and nothing must count as sent — retype, bounded.
    act_empty = plan_facebook_dating_fixed_first_contact(
        "send 2 first contact messages on Facebook Dating",
        tree,
        ["Type photo comment"],
        state=st,
        dry_run=False,
        message=PHOTO_COMMENT_TEXT,
        target=2,
    )
    assert act_empty is not None
    assert act_empty.get("action") == "type"
    assert st["bulk_message_new"]["done"] == 0

    # Only once the line is verified in the box does Send happen.
    typed_tree = (FIX / "fb_dating_comment_typed_r46.xml").read_text(encoding="utf-8")
    act2 = plan_facebook_dating_fixed_first_contact(
        "send 2 first contact messages on Facebook Dating",
        typed_tree,
        ["Type photo comment"],
        state=st,
        dry_run=False,
        message=PHOTO_COMMENT_TEXT,
        target=2,
    )
    assert act2 is not None
    assert act2.get("action") == "tap"
    assert (act2.get("x"), act2.get("y")) == SEND_XY
    assert (act2.get("x"), act2.get("y")) != LIKE_XY
    # Count after the sheet closes / next profile appears, not at the Send tap.
    assert st["bulk_message_new"]["done"] == 0
    assert st["bulk_message_new"].get("awaiting_send")
    assert act2.get("_no_llm_handoff") is True


def test_profile_taps_heart_to_open_comment_box():
    # Video (24 Nov 2026): the purple heart on the profile opens the
    # "Say something about this photo..." box — it never sends a bare like.
    tree = (FIX / "fb_dating_profile_ellie.xml").read_text(encoding="utf-8")
    act = plan_facebook_dating_fixed_first_contact(
        "send 2 first contact messages on Facebook Dating",
        tree,
        ["Opened Facebook Dating", "Tap Facebook Dating card photo"],
        state={"bulk_message_new": {"done": 0}},
        dry_run=False,
        message=PHOTO_COMMENT_TEXT,
        target=2,
    )
    assert act is not None
    assert act.get("action") == "tap"
    assert (act.get("x"), act.get("y")) != LIKE_XY
    assert "photo" in (act.get("reason") or "").lower()  # r53: never the heart


def test_explore_backs_out_not_spotlight_or_crush():
    tree = (FIX / "fb_dating_explore.xml").read_text(encoding="utf-8")
    act = plan_facebook_dating_fixed_first_contact(
        "send 2 first contact messages on Facebook Dating",
        tree,
        ["Opened Facebook Dating"],
        state={"bulk_message_new": {"done": 0}},
        dry_run=False,
        message=PHOTO_COMMENT_TEXT,
        target=2,
    )
    assert act is not None
    assert act.get("action") == "press_button"
    assert act.get("button") == "back"
    reason = (act.get("reason") or "").lower()
    assert "spotlight" in reason or "crush" in reason
    assert act.get("x") is None


def test_quoted_custom_mac_line_is_used():
    from backend.facebook_dating_fixed_first_contact import comment_text

    # Known bank lines in quotes are library hints; a custom Mac quote wins.
    assert (
        comment_text(
            'send 1 first contact messages on facebook dating "totally custom mac line"',
            "",
        )
        == "totally custom mac line"
    )


def test_counts_send_after_sheet_closes_not_at_tap():
    """Count when the next profile is on the deck, not when Send is tapped."""
    typed = (FIX / "fb_dating_comment_typed_r46.xml").read_text(encoding="utf-8")
    profile = (FIX / "fb_dating_profile_ellie.xml").read_text(encoding="utf-8")
    st = {
        "bulk_message_new": {
            "done": 0,
            "typed": True,
            "text": "hi miss you look beautiful",
        }
    }
    inst = "send 1 first contact messages on Facebook Dating"
    act = plan_facebook_dating_fixed_first_contact(
        inst,
        typed,
        ["Type photo comment"],
        state=st,
        dry_run=False,
        message="hi miss you look beautiful",
        target=1,
    )
    assert act is not None and act.get("action") == "tap"
    assert (act.get("x"), act.get("y")) == SEND_XY
    assert st["bulk_message_new"]["done"] == 0
    assert st["bulk_message_new"].get("awaiting_send")
    # Sheet closed, Ellie is on the profile — that is the send landing.
    act2 = plan_facebook_dating_fixed_first_contact(
        inst,
        profile,
        ["Facebook Dating Send"],
        state=st,
        dry_run=False,
        message="hi miss you look beautiful",
        target=1,
    )
    assert st["bulk_message_new"]["done"] == 1
    # The new card (Ellie) is the next person, not the one just messaged.
    assert "Ellie" not in (st["bulk_message_new"].get("sent_names") or [])
    assert act2 is not None and act2.get("action") == "done"


def test_skips_leah_with_no_thanks_never_heart():
    tree = (FIX / "fb_dating_profile_ellie.xml").read_text(encoding="utf-8")
    # Same profile chrome, Leah's name on the photo button.
    tree = tree.replace("Ellie, 21", "Leah, 24").replace("Ellie", "Leah")
    from backend.facebook_dating_fixed_first_contact import _profile_name, PASS_XY

    assert _profile_name(tree) == "Leah"
    st = {"bulk_message_new": {"done": 0}}
    act = plan_facebook_dating_fixed_first_contact(
        "send 1 first contact messages on Facebook Dating",
        tree,
        ["Opened Facebook Dating"],
        state=st,
        dry_run=False,
        message="good evening beautiful",
        target=1,
    )
    assert act is not None
    assert act.get("action") == "tap"
    assert (act.get("x"), act.get("y")) == PASS_XY
    assert (act.get("x"), act.get("y")) != LIKE_XY
    assert (
        "No Thanks" in (act.get("reason") or "")
        or "already messaged" in (act.get("reason") or "").lower()
    )
    assert st["bulk_message_new"]["done"] == 0
    assert act.get("_no_llm_handoff") is True


def test_send_ignores_nav_level_send_node():
    from backend.facebook_dating_fixed_first_contact import _send_center

    tree = (
        '<hierarchy packages="com.facebook.katana"><w p="com.facebook.katana" a="1">'
        '<n e="1" f="1" h="Say something about this photo..." t="hi miss you look beautiful" '
        'xy="500,2200" b="[40,2150][900,2250]" />'
        '<n d="Send" c="1" xy="985,2191" b="[930,2140][1040,2250]" />'
        "</w></hierarchy>"
    )
    assert _send_center(tree) is None


def test_front_card_name_is_last_in_stack():
    """fb4: tree listed Meghan then Leah; the screenshot was Leah."""
    from backend.facebook_dating_fixed_first_contact import _profile_name, PASS_XY

    tree = (
        '<hierarchy packages="com.facebook.katana"><w p="com.facebook.katana" a="1">'
        '<n d="Profile picture, Meghan, 23" i="profile_photo_tetra_pressable_test_id" '
        'c="1" xy="540,723" b="[0,75][1080,1371]" />'
        '<n t="Meghan, 23" xy="198,1464" b="[32,1445][365,1484]" />'
        '<n d="No, Thanks" c="1" xy="340,2116" b="[246,2022][435,2211]" />'
        '<n d="Like" c="1" xy="739,2116" b="[645,2022][834,2211]" />'
        '<n d="Profile picture, Leah, 22" i="profile_photo_tetra_pressable_test_id" '
        'c="1" xy="540,723" b="[0,75][1080,1371]" />'
        '<n t="Leah, 22" xy="152,1464" b="[32,1445][273,1484]" />'
        '<n d="No, Thanks" c="1" xy="340,2116" b="[246,2022][435,2211]" />'
        '<n d="Like" c="1" xy="739,2116" b="[645,2022][834,2211]" />'
        "</w></hierarchy>"
    )
    assert _profile_name(tree) == "Leah"
    st = {"bulk_message_new": {"done": 0}}
    act = plan_facebook_dating_fixed_first_contact(
        'send 1 first contact messages on facebook dating "good evening beautiful"',
        tree,
        ["Opened Facebook Dating"],
        state=st,
        dry_run=False,
        message="good evening beautiful",
        target=1,
    )
    assert act["action"] == "tap" and (act["x"], act["y"]) == PASS_XY
    assert (act["x"], act["y"]) != LIKE_XY
    assert st["bulk_message_new"]["done"] == 0


def test_unconfirmed_send_with_text_still_in_box_does_not_count():
    """fb4: after Send, the box still had the line (keyboard closed)."""
    tree = (
        '<hierarchy packages="com.facebook.katana"><w p="com.facebook.katana" a="1">'
        '<n t="good evening beautiful" h="Say something about this photo..." e="1" '
        'c="1" xy="472,2190" b="[74,2164][871,2217]" />'
        '<n d="Send" c="1" xy="980,2195" b="[923,2138][1038,2253]" />'
        "</w></hierarchy>"
    )
    st = {
        "bulk_message_new": {
            "done": 0,
            "awaiting_send": True,
            "pending_count": True,
            "pending_name": "Meghan",
            "counted_this_send": False,
            "text": "good evening beautiful",
        }
    }
    act = plan_facebook_dating_fixed_first_contact(
        "send 1 first contact messages on facebook dating",
        tree,
        ["Facebook Dating Send"],
        state=st,
        dry_run=False,
        message="good evening beautiful",
        target=1,
    )
    assert st["bulk_message_new"]["done"] == 0
    assert act.get("action") != "done"
    assert act.get("fastpath_step") in (
        "fb_dating_fc_focus_send",
        "fb_dating_fc_send_retry",
        "fb_dating_fc_focus_box",
    )


def test_blank_tree_after_send_waits_and_does_not_count():
    blank = '<hierarchy packages="com.facebook.katana"><w p="com.facebook.katana"><n t="x" xy="5,5"/></w></hierarchy>'
    st = {
        "bulk_message_new": {
            "done": 0,
            "awaiting_send": True,
            "pending_count": True,
            "pending_name": "Meghan",
            "counted_this_send": False,
            "text": "good evening beautiful",
        }
    }
    act = plan_facebook_dating_fixed_first_contact(
        "send 1 first contact messages on facebook dating",
        blank,
        ["Facebook Dating Send"],
        state=st,
        dry_run=False,
        message="good evening beautiful",
        target=1,
    )
    assert act["action"] == "wait"
    assert act["fastpath_step"] == "fb_dating_fc_wait_confirm"
    assert st["bulk_message_new"]["done"] == 0


def test_leftover_draft_is_cleared_never_sent():
    typed = (FIX / "fb_dating_comment_typed_r46.xml").read_text(encoding="utf-8")
    # Use tonight's line so the leftover matches the stuck opener text.
    typed = typed.replace("hi miss you look beautiful", "good evening beautiful")
    st = {"bulk_message_new": {"done": 0, "text": "good evening beautiful"}}
    inst = "send 1 first contact messages on facebook dating"
    act = plan_facebook_dating_fixed_first_contact(
        inst,
        typed,
        ["Opened Facebook Dating"],
        state=st,
        dry_run=False,
        message="good evening beautiful",
        target=1,
    )
    assert act["fastpath_step"] == "fb_dating_fc_clear_draft"
    assert act.get("_clear_only") and act.get("clear")
    assert st["bulk_message_new"]["done"] == 0
    # After the clear, Back — never Send.
    empty = typed.replace('t="good evening beautiful"', 't=""')
    act2 = plan_facebook_dating_fixed_first_contact(
        inst,
        empty,
        ["Clear leftover"],
        state=st,
        dry_run=False,
        message="good evening beautiful",
        target=1,
    )
    # empty box is a fresh sheet — type is OK; or if cleared_draft still set
    # and box empty, we should not send leftover. Either type (new attempt)
    # or back is fine; never a send of the leftover while cleared_draft.
    assert act2.get("action") != "tap" or (act2.get("x"), act2.get("y")) != SEND_XY
    assert st["bulk_message_new"]["done"] == 0


def test_partial_sheet_after_send_waits_does_not_count():
    """fb5: a comment-sheet dump with no readable box must not count as sent."""
    tree = (
        '<hierarchy packages="com.facebook.katana"><w p="com.facebook.katana" a="1">'
        '<n t="Say something about this photo..." xy="472,1320" b="[74,1270][871,1370]" />'
        '<n d="Send" c="1" xy="980,1329" b="[923,1272][1038,1387]" />'
        "</w></hierarchy>"
    )
    st = {
        "bulk_message_new": {
            "done": 0,
            "awaiting_send": True,
            "pending_count": True,
            "pending_name": "Zoe",
            "counted_this_send": False,
            "typed": True,
            "text": "good evening beautiful",
        }
    }
    act = plan_facebook_dating_fixed_first_contact(
        "send 1 first contact messages on facebook dating",
        tree,
        ["Facebook Dating Send"],
        state=st,
        dry_run=False,
        message="good evening beautiful",
        target=1,
    )
    assert st["bulk_message_new"]["done"] == 0
    assert act.get("action") != "done"


def test_false_count_is_rolled_back_if_text_still_in_box():
    """fb6: done was set after focus_send while the line was still in the box."""
    tree = (
        '<hierarchy packages="com.facebook.katana"><w p="com.facebook.katana" a="1">'
        '<n t="good evening beautiful" h="Say something about this photo..." e="1" '
        'f="1" c="1" xy="472,1324" b="[74,1298][871,1351]" />'
        '<n d="Send" c="1" xy="980,1329" b="[923,1272][1038,1387]" />'
        "</w></hierarchy>"
    )
    st = {
        "bulk_message_new": {
            "done": 1,
            "awaiting_send": False,
            "pending_count": False,
            "pending_name": "Kirsty",
            "counted_this_send": True,
            "typed": True,
            "send_retry": 1,
            "text": "good evening beautiful",
        }
    }
    act = plan_facebook_dating_fixed_first_contact(
        "send 1 first contact messages on facebook dating",
        tree,
        ["Open the keyboard so Send sits above the nav"],
        state=st,
        dry_run=False,
        message="good evening beautiful",
        target=1,
    )
    assert st["bulk_message_new"]["done"] == 0
    assert act.get("action") != "done"
    assert act.get("fastpath_step") in (
        "fb_dating_fc_send_retry",
        "fb_dating_fc_send",
        "fb_dating_fc_focus_send",
        "fb_dating_fc_not_sent",
    )
