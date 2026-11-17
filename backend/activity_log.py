"""Shared live-activity step logging for Dating / Social / Normal jobs."""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("mobilerun.activity")


def append_step(
    state: Dict[str, Any],
    *,
    action: str,
    reason: str = "",
    package: str = "",
    screen: str = "",
    ok: bool = True,
    screenshot_key: Optional[str] = None,
    verify: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Append one activity entry onto job.state.steps_detail (mutates state)."""
    steps: List[Dict[str, Any]] = list(state.get("steps_detail") or [])
    step_n = int(state.get("steps") or 0)
    if step_n <= 0:
        step_n = len(steps) + 1
    entry = {
        "n": step_n,
        "action": action,
        "reason": reason,
        "ok": ok,
        "package": package or "",
        "screen": screen or package or "",
        "screenshot_key": screenshot_key,
        "verify": verify,
        "dry_run": bool(dry_run),
        "ts": int(time.time()),
    }
    steps.append(entry)
    state["steps_detail"] = steps[-60:]
    state["last_action"] = action
    state["last_reason"] = reason
    state["last_package"] = package
    state["last_screen"] = entry["screen"]
    return entry


def capture_device_context(device_id: str) -> Dict[str, Any]:
    """Best-effort UI package + screenshot for activity thumbnails."""
    out: Dict[str, Any] = {"package": "", "tree_chars": 0, "screenshot_b64": None}
    if not device_id or device_id == "default":
        return out
    try:
        from device_rpc import call_device
    except ImportError:
        from backend.device_rpc import call_device  # type: ignore

    try:
        raw = call_device(device_id, "get_ui_tree", {}, timeout_s=12) or ""
        if isinstance(raw, dict):
            out["package"] = str(raw.get("package") or "")
            tree = raw.get("tree") or ""
            out["tree_chars"] = int(raw.get("chars") or len(str(tree)))
            if not out["package"] and isinstance(tree, str):
                # fallback: first package= attr
                import re

                m = re.search(r'package="([^"]+)"', tree)
                if m:
                    out["package"] = m.group(1)
        elif isinstance(raw, str):
            out["tree_chars"] = len(raw)
    except Exception as e:
        logger.warning("activity get_ui_tree failed: %s", e)

    try:
        from cloud_agent import _fetch_screenshot_b64, _store_step_screenshot
    except ImportError:
        try:
            from backend.cloud_agent import (  # type: ignore
                _fetch_screenshot_b64,
                _store_step_screenshot,
            )
        except ImportError:
            return out

    try:
        out["screenshot_b64"] = _fetch_screenshot_b64(device_id)
    except Exception as e:
        logger.warning("activity screenshot failed: %s", e)
    return out


def store_screenshot(job_id: str, step_n: int, b64: Optional[str]) -> Optional[str]:
    if not b64:
        return None
    try:
        from cloud_agent import _store_step_screenshot
    except ImportError:
        from backend.cloud_agent import _store_step_screenshot  # type: ignore

    return _store_step_screenshot(job_id, step_n, b64)


def steps_with_urls(raw_steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Attach short-lived presigned screenshot URLs for the web live view."""
    bucket = os.environ.get("SCREENSHOT_BUCKET") or ""
    out: List[Dict[str, Any]] = []
    client = None
    if bucket:
        try:
            import boto3

            client = boto3.client("s3")
        except Exception:
            client = None
    for s in raw_steps or []:
        if not isinstance(s, dict):
            continue
        item = dict(s)
        key = s.get("screenshot_key")
        url = None
        if key and client and bucket:
            try:
                url = client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": bucket, "Key": key},
                    ExpiresIn=3600,
                )
            except Exception:
                url = None
        item["screenshot_url"] = url
        out.append(item)
    return out


def activity_payload_from_job(job: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not job:
        return {
            "job_id": None,
            "status": "idle",
            "steps": [],
            "current_step": 0,
            "package": None,
            "last_action": None,
        }
    st = job.get("state") or {}
    steps = steps_with_urls(list(st.get("steps_detail") or []))
    return {
        "job_id": job.get("job_id"),
        "status": job.get("status"),
        "mode": job.get("kind") or job.get("mode") or "agent",
        "dry_run": bool(job.get("dry_run")),
        "device_id": job.get("device_id"),
        "current_step": int(st.get("steps") or 0),
        "package": st.get("last_package") or st.get("current_app"),
        "screen": st.get("last_screen"),
        "last_action": st.get("last_action"),
        "last_reason": st.get("last_reason"),
        "steps": steps,
        "openers_sent": st.get("openers_sent"),
        "replies_sent": st.get("replies_sent"),
        "swipes_done": st.get("swipes_done"),
        "updated_at": job.get("updated_at") or job.get("created_at"),
    }
