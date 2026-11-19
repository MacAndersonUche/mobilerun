"""Seed 'hi baby' bubbles must not satisfy outgoing verification."""

from backend.dm_heuristics import outgoing_bubble_present


def test_seed_old_outgoing_does_not_count():
    tree = """
    <n t="hi baby" d="Old outgoing message: hi baby" xy="900,400" e="0"/>
    <n t="Type a message" h="Type a message" i="entry" xy="200,2000" e="1"/>
    """
    assert outgoing_bubble_present(tree, "hi baby") is False


def test_new_outgoing_counts():
    tree = """
    <n t="hi baby" d="Old outgoing message: hi baby" xy="900,400" e="0"/>
    <n t="hi baby" d="New outgoing message 1: hi baby" xy="900,550" e="0"/>
    <n t="Type a message" h="Type a message" i="entry" xy="200,2000" e="1"/>
    """
    assert outgoing_bubble_present(tree, "hi baby") is True


def test_concatenated_contact_plus_message_rejected():
    tree = """
    <n t="Precious Achalugohi baby" d="New outgoing message 2: Precious Achalugohi baby" xy="700,600" e="0"/>
    """
    assert outgoing_bubble_present(tree, "hi baby") is False


def test_real_whatsapp_unmarked_bubble_still_counts():
    tree = """
    <n t="hi baby" i="message_text" xy="900,900" e="0"/>
    """
    assert outgoing_bubble_present(tree, "hi baby") is True
