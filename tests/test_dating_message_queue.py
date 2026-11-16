"""Tests for sequential message queue."""

import pytest
import asyncio
from mobilerun.dating.message_queue import (
    SequentialMessageQueue,
    QueuedMessage,
    MessageType,
)


@pytest.fixture
def message_queue():
    """Create a test message queue."""
    return SequentialMessageQueue(min_gap_sec=1, max_gap_sec=2, review_mode=False)


@pytest.fixture
def review_queue():
    """Create a queue with review mode enabled."""
    return SequentialMessageQueue(min_gap_sec=1, max_gap_sec=2, review_mode=True)


def create_test_message(msg_id: str, msg_type: MessageType = MessageType.REPLY):
    """Helper to create test message."""
    return QueuedMessage(
        id=msg_id,
        app_name="Hinge",
        package_name="co.hinge.app",
        conversation_id="conv_123",
        profile_name="TestUser",
        message_type=msg_type,
        message_content="Hey there!",
    )


@pytest.mark.asyncio
async def test_enqueue_message(message_queue):
    """Test adding messages to queue."""
    msg = create_test_message("msg1")
    await message_queue.enqueue(msg)

    assert message_queue.get_queue_size() == 1


@pytest.mark.asyncio
async def test_sequential_processing(message_queue):
    """Test that messages are processed sequentially."""
    sent_messages = []

    async def mock_send(message):
        sent_messages.append(message.id)
        await asyncio.sleep(0.1)

    # Enqueue 3 messages
    for i in range(3):
        msg = create_test_message(f"msg{i}")
        await message_queue.enqueue(msg)

    # Process all
    stop_event = asyncio.Event()

    async def process_for_time():
        await asyncio.sleep(5)
        stop_event.set()

    await asyncio.gather(
        message_queue.process_queue(mock_send, stop_event),
        process_for_time(),
    )

    # All 3 should be sent
    assert len(sent_messages) == 3
    assert sent_messages == ["msg0", "msg1", "msg2"]


@pytest.mark.asyncio
async def test_conversation_gap(message_queue):
    """Test gap between messages."""
    gap = message_queue.get_conversation_gap()
    assert 1 <= gap <= 2


@pytest.mark.asyncio
async def test_review_mode(review_queue):
    """Test review mode workflow."""
    msg = create_test_message("msg1")
    await review_queue.enqueue(msg)

    # Should require review
    pending = review_queue.get_pending_review()
    assert len(pending) == 1
    assert pending[0].requires_review

    # Not ready to send yet
    ready = review_queue.get_ready_to_send()
    assert len(ready) == 0

    # Approve it
    approved = await review_queue.approve("msg1")
    assert approved

    # Now ready to send
    ready = review_queue.get_ready_to_send()
    assert len(ready) == 1


@pytest.mark.asyncio
async def test_reject_message(review_queue):
    """Test rejecting a message."""
    msg = create_test_message("msg1")
    await review_queue.enqueue(msg)

    assert review_queue.get_queue_size() == 1

    rejected = await review_queue.reject("msg1")
    assert rejected
    assert review_queue.get_queue_size() == 0


@pytest.mark.asyncio
async def test_update_message(review_queue):
    """Test updating message content."""
    msg = create_test_message("msg1")
    await review_queue.enqueue(msg)

    updated = await review_queue.update("msg1", "New content!")
    assert updated

    pending = review_queue.get_pending_review()
    assert pending[0].message_content == "New content!"


@pytest.mark.asyncio
async def test_no_review_mode(message_queue):
    """Test queue without review mode."""
    msg = create_test_message("msg1")
    await message_queue.enqueue(msg)

    # Should be ready immediately (no review required)
    ready = message_queue.get_ready_to_send()
    assert len(ready) == 1
    assert not ready[0].requires_review


@pytest.mark.asyncio
async def test_process_next(message_queue):
    """Test processing next message."""
    sent = []

    async def mock_send(message):
        sent.append(message.id)

    # Enqueue 2 messages
    await message_queue.enqueue(create_test_message("msg1"))
    await message_queue.enqueue(create_test_message("msg2"))

    # Process first
    result = await message_queue.process_next(mock_send)
    assert result.id == "msg1"
    assert len(sent) == 1
    assert message_queue.get_queue_size() == 1

    # Process second
    result = await message_queue.process_next(mock_send)
    assert result.id == "msg2"
    assert len(sent) == 2
    assert message_queue.get_queue_size() == 0


@pytest.mark.asyncio
async def test_clear_queue(message_queue):
    """Test clearing queue."""
    await message_queue.enqueue(create_test_message("msg1"))
    await message_queue.enqueue(create_test_message("msg2"))

    assert message_queue.get_queue_size() == 2

    message_queue.clear()
    assert message_queue.get_queue_size() == 0


@pytest.mark.asyncio
async def test_opener_vs_reply_types():
    """Test differentiating opener vs reply messages."""
    queue = SequentialMessageQueue(review_mode=False)

    opener = create_test_message("opener1", MessageType.OPENER)
    reply = create_test_message("reply1", MessageType.REPLY)

    await queue.enqueue(opener)
    await queue.enqueue(reply)

    assert queue.get_queue_size() == 2
    assert opener.message_type == MessageType.OPENER
    assert reply.message_type == MessageType.REPLY
