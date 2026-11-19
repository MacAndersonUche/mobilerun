from backend.bulk_bench_heuristics import parse_bulk_goal, plan_bulk_swipe


def test_parse_bulk_swipe():
    g = parse_bulk_goal("tinder auto-swipe 50 profiles")
    assert g and g["kind"] == "swipe" and g["count"] == 50


def test_parse_bulk_message_bank_text():
    g = parse_bulk_goal('hinge auto-message 50 matches tell them "hi baby"')
    assert g and g["kind"] == "message"
    assert g["message"] == "hi baby"
    assert g["count"] == 50


def test_bulk_swipe_like_and_dismiss():
    tree = """
    <n t="Profile01" d="Profile Profile01" xy="540,900" e="0"/>
    <n t="" d="Like" xy="860,2100" c="1" e="0"/>
    """
    st: dict = {}
    act = plan_bulk_swipe(
        "tinder auto-swipe 50 profiles", tree, [], state=st, package="com.tinder"
    )
    assert act and act.get("action") == "tap"
    assert st.get("bulk_swipe", {}).get("done") == 1


def test_out_of_likes_stops():
    tree = """
    <n t="Out of likes" d="Out of likes" xy="540,900" e="0"/>
    <n t="Maybe later" d="Maybe later" xy="540,1400" c="1" e="0"/>
    """
    st = {"bulk_swipe": {"done": 40, "target": 50}}
    act = plan_bulk_swipe(
        "tinder auto-swipe 50 profiles", tree, [], state=st, package="com.tinder"
    )
    assert act and act.get("action") == "done"
    assert act.get("stopped_reason") == "out_of_likes"
