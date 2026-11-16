"""Notify Mac about Needs-you items: UI, APK push, optional SES email."""

from __future__ import annotations

import logging
import os
from typing import Any, Awaitable, Callable, Dict, Optional

from mobilerun.needs_you.queue import NeedsYouItem

logger = logging.getLogger("mobilerun.needs_you.notify")


async def notify_needs_you(
    item: NeedsYouItem,
    *,
    badge_count: int,
    broadcast_ui: Optional[Callable[[str, Dict[str, Any]], Awaitable[Any]]] = None,
    send_to_device: Optional[Callable[[str, Dict[str, Any]], Awaitable[bool]]] = None,
    device_id: Optional[str] = None,
    email_enabled: bool = False,
    email_to: str = "macandersonuche@yahoo.com",
) -> Dict[str, Any]:
    """Fan-out notifications. SES is off by default."""
    result = {"ui": False, "apk": False, "email": False}
    payload = {
        "type": "needs_you",
        "badge": badge_count,
        "item": item.to_dict(),
    }

    if broadcast_ui:
        try:
            await broadcast_ui(device_id or "all", payload)
            result["ui"] = True
        except Exception as e:
            logger.warning("UI notify failed: %s", e)

    if send_to_device and device_id:
        try:
            ok = await send_to_device(
                device_id,
                {
                    "type": "push_notification",
                    "title": "Needs you",
                    "body": f"{item.app_name}: {item.contact_name} — confirm reply",
                    "badge": badge_count,
                    "item_id": item.id,
                },
            )
            result["apk"] = bool(ok)
        except Exception as e:
            logger.warning("APK notify failed: %s", e)

    if email_enabled:
        result["email"] = _send_ses_email(email_to, item, badge_count)

    return result


def _send_ses_email(to_addr: str, item: NeedsYouItem, badge: int) -> bool:
    if os.environ.get("NEEDS_YOU_EMAIL", "false").lower() not in (
        "1",
        "true",
        "yes",
    ):
        return False
    try:
        import boto3

        client = boto3.client(
            "ses", region_name=os.environ.get("AWS_REGION", "eu-west-2")
        )
        body = (
            f"Needs you ({badge} pending)\n\n"
            f"App: {item.app_name}\n"
            f"Contact: {item.contact_name}\n"
            f"Reasons: {', '.join(item.reasons)}\n\n"
            f"Inbound: {item.inbound_preview}\n\n"
            f"Draft:\n{item.draft_reply}\n"
        )
        client.send_email(
            Source=os.environ.get("SES_FROM", to_addr),
            Destination={"ToAddresses": [to_addr]},
            Message={
                "Subject": {"Data": f"[Mobilerun] Needs you — {item.contact_name}"},
                "Body": {"Text": {"Data": body}},
            },
        )
        return True
    except Exception as e:
        logger.warning("SES email failed: %s", e)
        return False
