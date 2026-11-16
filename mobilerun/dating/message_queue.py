"""Sequential message queue for human-like dating app messaging."""

import asyncio
import random
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional
from enum import Enum


class MessageType(Enum):
    """Type of message to send."""

    OPENER = "opener"  # First message to new match
    REPLY = "reply"  # Reply to existing conversation


@dataclass
class QueuedMessage:
    """A message queued for sending."""

    id: str
    app_name: str
    package_name: str
    conversation_id: str
    profile_name: str
    message_type: MessageType
    message_content: str
    requires_review: bool = False
    created_at: Optional[str] = None
    approved: bool = False

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now().isoformat()


class SequentialMessageQueue:
    """
    Sequential message queue with human-like gaps between sends.

    Processes messages one conversation at a time with randomized
    delays between each send to mimic human behavior.
    """

    def __init__(
        self,
        min_gap_sec: int = 30,
        max_gap_sec: int = 180,
        review_mode: bool = True,
    ):
        self.min_gap_sec = min_gap_sec
        self.max_gap_sec = max_gap_sec
        self.review_mode = review_mode

        self._queue: List[QueuedMessage] = []
        self._processing = False
        self._lock = asyncio.Lock()

    async def enqueue(self, message: QueuedMessage) -> None:
        """Add a message to the queue."""
        async with self._lock:
            message.requires_review = self.review_mode
            self._queue.append(message)

    async def approve(self, message_id: str) -> bool:
        """Approve a message for sending."""
        async with self._lock:
            for msg in self._queue:
                if msg.id == message_id:
                    msg.approved = True
                    return True
            return False

    async def reject(self, message_id: str) -> bool:
        """Remove a message from the queue."""
        async with self._lock:
            original_len = len(self._queue)
            self._queue = [msg for msg in self._queue if msg.id != message_id]
            return len(self._queue) < original_len

    async def update(self, message_id: str, new_content: str) -> bool:
        """Update message content."""
        async with self._lock:
            for msg in self._queue:
                if msg.id == message_id:
                    msg.message_content = new_content
                    return True
            return False

    def get_pending_review(self) -> List[QueuedMessage]:
        """Get messages requiring review."""
        return [msg for msg in self._queue if msg.requires_review and not msg.approved]

    def get_ready_to_send(self) -> List[QueuedMessage]:
        """Get messages ready to send (approved or no review required)."""
        return [
            msg
            for msg in self._queue
            if (not msg.requires_review) or (msg.requires_review and msg.approved)
        ]

    def get_queue_size(self) -> int:
        """Get total queue size."""
        return len(self._queue)

    async def process_next(self, send_callback) -> Optional[QueuedMessage]:
        """
        Process next ready message from queue.

        Args:
            send_callback: Async function to call to actually send the message

        Returns:
            The message that was sent, or None if queue is empty
        """
        async with self._lock:
            ready = self.get_ready_to_send()
            if not ready:
                return None

            # Get next message
            message = ready[0]
            self._queue.remove(message)

        # Send message (outside lock)
        try:
            await send_callback(message)
        except Exception as e:
            # On error, don't re-queue, just log
            print(f"Failed to send message {message.id}: {e}")

        return message

    def get_conversation_gap(self) -> float:
        """Get randomized gap between conversations in seconds."""
        return random.uniform(self.min_gap_sec, self.max_gap_sec)

    async def process_queue(self, send_callback, stop_event: asyncio.Event):
        """
        Process queue sequentially with human-like gaps.

        Args:
            send_callback: Async function to send messages
            stop_event: Event to signal stopping
        """
        if self._processing:
            return

        self._processing = True

        try:
            while not stop_event.is_set():
                message = await self.process_next(send_callback)

                if message is None:
                    # Queue empty, wait and check again
                    await asyncio.sleep(5)
                    continue

                # Human-like gap before next message
                gap = self.get_conversation_gap()
                await asyncio.sleep(gap)

        finally:
            self._processing = False

    def clear(self):
        """Clear all queued messages."""
        self._queue.clear()
