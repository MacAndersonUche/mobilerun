"""WebSocket-based device driver for wireless control."""

import asyncio
import base64
import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("mobilerun.websocket_driver")


class WebSocketDeviceDriver:
    """
    Device driver that communicates with Android app over WebSocket.
    
    Implements the same interface as AndroidDriver but sends commands
    over WebSocket instead of ADB.
    """

    def __init__(self, websocket, device_id: str):
        self.websocket = websocket
        self.device_id = device_id
        self._response_futures: Dict[str, asyncio.Future] = {}
        self._request_id = 0

    async def connect(self):
        """Connection is already established via WebSocket."""
        logger.info(f"WebSocket driver connected to {self.device_id}")

    async def disconnect(self):
        """Close the WebSocket connection."""
        try:
            await self.websocket.close()
        except Exception as e:
            logger.warning(f"Error closing websocket: {e}")

    async def _send_command(
        self, command: str, params: Optional[Dict[str, Any]] = None, timeout: float = 30.0
    ) -> Any:
        """Send a command and wait for response."""
        self._request_id += 1
        request_id = f"req_{self._request_id}"

        message = {"type": "command", "command": command, "request_id": request_id}

        if params:
            message["params"] = params

        # Create future for response
        future = asyncio.Future()
        self._response_futures[request_id] = future

        try:
            # Send command
            await self.websocket.send_json(message)

            # Wait for response
            result = await asyncio.wait_for(future, timeout=timeout)
            return result

        except asyncio.TimeoutError:
            self._response_futures.pop(request_id, None)
            raise TimeoutError(f"Command {command} timed out after {timeout}s")
        except Exception as e:
            self._response_futures.pop(request_id, None)
            raise RuntimeError(f"Command {command} failed: {e}")

    def handle_response(self, message: Dict[str, Any]):
        """Handle a response from the device."""
        request_id = message.get("request_id")
        if not request_id or request_id not in self._response_futures:
            return

        future = self._response_futures.pop(request_id)
        if message.get("error"):
            future.set_exception(RuntimeError(message["error"]))
        else:
            future.set_result(message.get("result"))

    # Device control methods matching AndroidDriver interface

    async def screenshot(self) -> bytes:
        """Capture screenshot."""
        result = await self._send_command("screenshot")
        if isinstance(result, str):
            # Base64 encoded screenshot
            return base64.b64decode(result)
        elif isinstance(result, bytes):
            return result
        else:
            raise ValueError(f"Unexpected screenshot result type: {type(result)}")

    async def get_ui_tree(self) -> str:
        """Get UI accessibility tree."""
        result = await self._send_command("get_ui_tree")
        return result if isinstance(result, str) else ""

    async def tap(self, x: int, y: int) -> None:
        """Tap at coordinates."""
        await self._send_command("tap", {"x": x, "y": y})

    async def swipe(
        self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300
    ) -> None:
        """Swipe gesture."""
        await self._send_command(
            "swipe", {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "duration_ms": duration_ms}
        )

    async def input_text(self, text: str, clear: bool = False) -> bool:
        """Input text."""
        result = await self._send_command("input_text", {"text": text, "clear": clear})
        return result if isinstance(result, bool) else True

    async def press_button(self, button: str) -> None:
        """Press system button (back, home, enter)."""
        await self._send_command("press_button", {"button": button})

    async def start_app(self, package: str) -> str:
        """Launch an app."""
        result = await self._send_command("start_app", {"package": package})
        return result if isinstance(result, str) else "OK"

    async def get_apps(self, include_system: bool = False) -> List[Dict[str, str]]:
        """Get list of installed apps."""
        result = await self._send_command("get_apps", {"include_system": include_system})
        return result if isinstance(result, list) else []

    async def get_device_info(self) -> Dict[str, str]:
        """Get device information."""
        result = await self._send_command("get_device_info")
        return result if isinstance(result, dict) else {}
