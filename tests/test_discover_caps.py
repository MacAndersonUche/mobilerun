"""Per-app daily caps on Discover messages + paste entry (Mac, 23 Nov 2026).

Caps: Hinge 50-100/day (default 50, safe end), Hily 5/day, BLK / Yubo /
Facebook Dating unlimited, everything else uncapped (no number given).
Counts verified sends only. Discover messages are pasted (humanize=False),
not typed character by character.
"""

from datetime import datetime, timezone
from pathlib import Path

from backend.bulk_bench_heuristics import (
    discover_send_verified,
    plan_bulk_message_new,
)
from backend.discover_caps import (
    clamp_discover_message_cap,
    discover_cap_reason,
    discover_message_cap,
    discover_messages_allowed,
)
from mobilerun.dating.config import (
    DatingModeConfig,
    discover_message_cap_for,
)
from mobilerun.dating.config import (
    clamp_discover_message_cap as cfg_clamp,
)
from mobilerun.dating.config import (
    discover_messages_allowed as cfg_allowed,
)

FIX = Path(__file__).resolve().parent / "fixtures" / "dm"


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


# --- cap table -----------------------------------------------------------

def test_hinge_cap_default_50_range_50_to_100():
    assert discover_message_cap("hinge") == 50
    assert clamp_discover_message_cap("hinge", 30) == 50
    assert clamp_discover_message_cap("hinge", 75) == 75
    assert clamp_discover_message_cap("hinge", 150) == 100
    assert discover_message_cap("hinge", override=75) == 75
    assert discover_message_cap("hinge", override=200) == 100


def test_hily_cap_5_fixed():
    assert discover_message_cap("hily") == 5
    assert clamp_discover_message_cap("hily", 3) == 5
    assert clamp_discover_message_cap("hily", 99) == 5


def test_blk_yubo_facebook_unlimited():
    for app in ("blk", "yubo", "facebook"):
        assert discover_message_cap(app) is None
        assert discover_messages_allowed(app, 10_000) is True


def test_apps_without_a_number_are_uncapped_not_invented():
    for app in ("bumble", "badoo", "tagged", "tinder"):
        assert discover_message_cap(app) is None


def test_allowed_counts_verified_sends_only():
    assert discover_messages_allowed("hinge", 49) is True
    assert discover_messages_allowed("hinge", 50) is False
    assert discover_messages_allowed("hily", 4) is True
    assert discover_messages_allowed("hily", 5) is False
    assert "50/50" in discover_cap_reason("hinge", 50).replace(" ", "")


def test_backend_caps_match_config_profiles():
    """The backend table and AppProfile fields must agree (no silent drift)."""
    cfg = DatingModeConfig()
    by_name = {p.name: p for p in cfg.apps}
    mapping = {
        "hinge": "Hinge",
        "hily": "Hily",
        "blk": "BLK",
        "yubo": "Yubo",
        "facebook": "Facebook",
    }
    for backend_key, profile_name in mapping.items():
        profile = by_name[profile_name]
        assert discover_message_cap_for(profile) == discover_message_cap(
            backend_key
        ), backend_key
        assert cfg_clamp(profile, 1_000) == clamp_discover_message_cap(
            backend_key, 1_000
        ), backend_key
        assert cfg_allowed(profile, 0) == discover_messages_allowed(
            backend_key, 0
        ), backend_key
    assert discover_message_cap_for(by_name["Hinge"]) == 50
    assert discover_message_cap_for(by_name["Hily"]) == 5
    assert discover_message_cap_for(by_name["BLK"]) is None


# --- verified-send detection ----------------------------------------------

_HILY_VERIFIED_TREE = """
<hierarchy><w p="com.hily.app">
 <n t="Ruth" xy="540,200"/>
 <n i="com.hily.app:id/threadTextMessageTrue" t="hey there" xy="700,700"/>
 <n e="1" t="" h="Type a message" xy="540,2100"/>
</w></hierarchy>
"""

_HILY_STILL_TYPING_TREE = """
<hierarchy><w p="com.hily.app">
 <n t="Ruth" xy="540,200"/>
 <n e="1" t="hey there" h="Type a message" xy="540,2100"/>
</w></hierarchy>
"""

_HINGE_SHEET_OPEN_TREE = """
<hierarchy><w p="co.hinge.app">
 <n t="Alex, 24" xy="540,400"/>
 <n t="Send Like" xy="540,2000" c="1"/>
 <n t="Add a comment" xy="540,1100"/>
 <n e="1" t="" h="Add a comment" xy="540,1800"/>
</w></hierarchy>
"""

_HINGE_DISCOVER_TREE = """
<hierarchy><w p="co.hinge.app">
 <n t="Alex, 24" xy="540,400"/>
 <n t="Discover" xy="200,2190" c="1"/>
</w></hierarchy>
"""


def test_hily_outgoing_bubble_counts_as_verified():
    assert discover_send_verified("hily", _HILY_VERIFIED_TREE, "hey there")


def test_hily_message_still_in_composer_not_verified():
    assert not discover_send_verified(
        "hily", _HILY_STILL_TYPING_TREE, "hey there"
    )


def test_hinge_sheet_closed_counts_as_verified():
    # Send Like landed: the sheet is gone on a readable tree.
    assert discover_send_verified(
        "hinge", _HINGE_DISCOVER_TREE, "hello miss"
    )


def test_hinge_sheet_still_open_not_verified():
    assert not discover_send_verified(
        "hinge", _HINGE_SHEET_OPEN_TREE, "hello miss"
    )


def test_empty_tree_verifies_nothing():
    assert not discover_send_verified("hily", "", "hey there")
    assert not discover_send_verified("hinge", "", "hello miss")


def test_bumble_fallback_composer_empty_counts():
    tree = """
    <hierarchy><w p="com.bumble.app">
     <n t="Maya" xy="540,200"/>
     <n e="1" t="" h="Message" xy="540,2100"/>
    </w></hierarchy>
    """
    assert discover_send_verified("bumble", tree, "hey there")


def test_bumble_fallback_no_composer_no_bubble_not_verified():
    tree = """
    <hierarchy><w p="com.bumble.app">
     <n t="Maya" xy="540,200"/>
    </w></hierarchy>
    """
    assert not discover_send_verified("bumble", tree, "hey there")


# --- cap gate in the Discover planner -------------------------------------

_SIMPLE_HILY_TREE = """
<hierarchy><w p="com.hily.app">
 <n t="Discover" xy="200,2190" c="1"/>
 <n t="Chats" xy="341,2190" c="1"/>
</w></hierarchy>
"""


def test_hily_cap_reached_refuses_new_contact():
    st = {
        "bulk_message_new": {
            "done": 0,
            "typed": False,
            "discover_verified_by_date": {_today(): 5},
        }
    }
    act = plan_bulk_message_new(
        'message "hey there" to 3 new profiles on Hily',
        _SIMPLE_HILY_TREE,
        ["Opened Hily"],
        state=st,
        package="com.hily.app",
    )
    assert act and act.get("action") == "fail"
    assert act.get("stopped_reason") == "discover_cap_reached"
    assert "5/5" in (act.get("reason") or "")


def test_hily_under_cap_proceeds():
    st = {
        "bulk_message_new": {
            "done": 0,
            "typed": False,
            "discover_verified_by_date": {_today(): 4},
        }
    }
    act = plan_bulk_message_new(
        'message "hey there" to 3 new profiles on Hily',
        _SIMPLE_HILY_TREE,
        ["Opened Hily"],
        state=st,
        package="com.hily.app",
    )
    assert act is not None
    assert act.get("stopped_reason") != "discover_cap_reached"


def test_dry_run_bypasses_the_cap_gate():
    st = {
        "bulk_message_new": {
            "done": 0,
            "typed": False,
            "discover_verified_by_date": {_today(): 5},
        }
    }
    act = plan_bulk_message_new(
        'message "hey there" to 3 new profiles on Hily',
        _SIMPLE_HILY_TREE,
        ["Opened Hily"],
        state=st,
        package="com.hily.app",
        dry_run=True,
    )
    assert act is not None
    assert act.get("stopped_reason") != "discover_cap_reached"


def test_verified_send_is_counted_on_next_step():
    st = {
        "bulk_message_new": {
            "done": 1,
            "typed": False,
            "awaiting_send_verify": True,
            "_last_sent_message": "hey there",
            "_send_verify_polls": 0,
        }
    }
    plan_bulk_message_new(
        'message "hey there" to 3 new profiles on Hily',
        _HILY_VERIFIED_TREE,
        ["Opened Hily"],
        state=st,
        package="com.hily.app",
    )
    bulk = st["bulk_message_new"]
    assert bulk.get("awaiting_send_verify") is False
    assert bulk.get("discover_verified_by_date", {}).get(_today()) == 1


def test_unverified_send_after_three_polls_does_not_count():
    st = {
        "bulk_message_new": {
            "done": 1,
            "typed": False,
            "awaiting_send_verify": True,
            "_last_sent_message": "hey there",
            "_send_verify_polls": 2,
        }
    }
    plan_bulk_message_new(
        'message "hey there" to 3 new profiles on Hily',
        _HILY_STILL_TYPING_TREE,
        ["Opened Hily"],
        state=st,
        package="com.hily.app",
    )
    bulk = st["bulk_message_new"]
    assert bulk.get("awaiting_send_verify") is False
    assert bulk.get("discover_verified_by_date", {}).get(_today(), 0) == 0


# --- paste entry on Discover ----------------------------------------------

def test_hinge_discover_comment_is_pasted_not_typed():
    act = plan_bulk_message_new(
        'message "hello miss" to 3 new profiles on Hinge',
        _HINGE_SHEET_OPEN_TREE,
        ["Opened Hinge", "tap - Focus Add a comment"],
        state={"bulk_message_new": {"done": 0, "typed": False}},
        package="co.hinge.app",
    )
    assert act and act.get("action") == "type"
    assert act.get("fastpath_step") == "bulk_hinge_new_type"
    assert act.get("humanize") is False


def test_blk_discover_opener_is_pasted_not_typed():
    tree = (FIX / "blk_thread.xml").read_text(encoding="utf-8")
    act = plan_bulk_message_new(
        'message "hi" to 3 new profiles on blk',
        tree,
        ["Opened BLK", "tap focus composer"],
        state={
            "bulk_message_new": {
                "done": 0,
                "typed": False,
                "current": "Maya",
            }
        },
        package="com.affinityapps.blk",
    )
    assert act and act.get("action") == "type"
    assert act.get("fastpath_step") == "bulk_new_free_type"
    assert act.get("humanize") is False
