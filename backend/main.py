"""
FastAPI backend for Mobilerun self-hosted control.
Supports both local (uvicorn) and Lambda (mangum) deployments.
"""

import asyncio
import base64
import io
import json
import logging
import os
import secrets
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import qrcode
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

# Add mobilerun to path for local runs
if Path(__file__).parent.parent.name == "mobilerun":
    sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.auth import (
    cognito_enabled,
    create_access_token,
    decode_bearer,
    optional_verify_token,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mobilerun.backend")

app = FastAPI(
    title="Mobilerun Backend",
    version="1.0.0",
    description="Self-hosted mobile automation backend",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, set to specific Netlify domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend if available
FRONTEND_DIR = os.getenv("FRONTEND_DIR")
if FRONTEND_DIR and Path(FRONTEND_DIR).exists():
    logger.info(f"Serving frontend from {FRONTEND_DIR}")
    try:
        app.mount(
            "/assets",
            StaticFiles(directory=Path(FRONTEND_DIR) / "assets"),
            name="assets",
        )
    except Exception as e:
        logger.warning(f"Failed to mount assets: {e}")

# In-memory state (for Lambda, consider DynamoDB)
connected_devices: Dict[str, Dict[str, Any]] = {}
active_runs: Dict[str, Dict[str, Any]] = {}
run_history: List[Dict[str, Any]] = []
websocket_clients: List[WebSocket] = []
pairing_tokens: Dict[str, Dict[str, Any]] = {}
# Long-lived device sessions for reconnect without USB / without re-scan
device_sessions: Dict[str, Dict[str, Any]] = {}  # session_token -> meta
device_websockets: Dict[str, WebSocket] = {}
# Device-code OAuth style linking (APK shows code → approve on web)
device_link_codes: Dict[str, Dict[str, Any]] = {}  # user_code -> meta


def _owner_key(auth: Optional[dict]) -> Optional[str]:
    if not auth:
        return None
    return (auth.get("email") or auth.get("user_id") or auth.get("sub") or "").lower() or None


def _device_visible_to(device: Dict[str, Any], auth: Optional[dict]) -> bool:
    """Only the owning account (Mac) can see/control a device."""
    if auth is None:
        return True  # unauthenticated mode
    owner = (device.get("owner") or "").lower()
    if not owner:
        return True  # legacy unpaired ownership — assign on next connect
    return owner == _owner_key(auth)


# === Frontend Routes ===

if FRONTEND_DIR and Path(FRONTEND_DIR).exists():

    @app.get("/", response_class=FileResponse)
    async def serve_index():
        """Serve the frontend index.html."""
        index_path = Path(FRONTEND_DIR) / "index.html"
        if index_path.exists():
            return FileResponse(index_path, media_type="text/html")
        raise HTTPException(status_code=404, detail="Frontend not found")

    @app.get("/{full_path:path}", response_class=FileResponse)
    async def serve_spa_routes(full_path: str):
        """Serve frontend for SPA routes (except API routes)."""
        if full_path.startswith("api/") or full_path.startswith("ws/"):
            raise HTTPException(status_code=404)

        # Try to serve the file if it exists
        file_path = Path(FRONTEND_DIR) / full_path
        if file_path.is_file():
            return FileResponse(file_path)

        # Otherwise serve index.html for SPA routing
        index_path = Path(FRONTEND_DIR) / "index.html"
        if index_path.exists():
            return FileResponse(index_path, media_type="text/html")
        raise HTTPException(status_code=404)


# === Models ===


class DeviceInfo(BaseModel):
    device_id: str
    name: str
    platform: str
    connected: bool
    connection_type: str
    last_seen: datetime
    route: Optional[str] = None
    latency_ms: Optional[float] = None
    permissions: Optional[Dict[str, Any]] = None


class PairingRequest(BaseModel):
    device_name: str
    platform: str = "android"


class TaskRequest(BaseModel):
    device_id: str
    instruction: str
    max_steps: int = 15
    reasoning: bool = False
    vision: bool = False
    # normal = general phone agent; dating uses /api/dating/*
    mode: str = "normal"
    # Shared humanizer: fast | balanced | careful
    speed_preset: str = "balanced"


class TaskStatus(BaseModel):
    task_id: str
    device_id: str
    instruction: str
    status: str
    current_step: int
    max_steps: int
    result: Optional[str] = None
    error: Optional[str] = None
    started_at: datetime
    completed_at: Optional[datetime] = None


class LLMConfig(BaseModel):
    provider: str
    model: str
    api_key: str
    temperature: float = 0.7
    max_tokens: int = 2048


class LoginRequest(BaseModel):
    username: str
    password: str


# === Auth Endpoints ===


@app.post("/api/auth/login")
async def login(request: LoginRequest):
    """Simple login endpoint (for development / local fallback)."""
    # In production prefer Cognito; local HS256 remains for offline serve.
    if request.username == "admin" and request.password == os.environ.get(
        "ADMIN_PASSWORD", "admin"
    ):
        token = create_access_token(
            {"sub": request.username, "email": f"{request.username}@local"}
        )
        return {"access_token": token, "token_type": "bearer"}

    raise HTTPException(status_code=401, detail="Invalid credentials")


@app.get("/api/auth/me")
async def auth_me(auth: Optional[dict] = Depends(optional_verify_token)):
    """Return current user claims + Cognito config flags."""
    return {
        "authenticated": auth is not None,
        "email": (auth or {}).get("email"),
        "user_id": (auth or {}).get("user_id"),
        "cognito_enabled": cognito_enabled(),
    }


class DeviceCodeStart(BaseModel):
    device_name: str = "Android"
    platform: str = "android"


class DeviceCodeApprove(BaseModel):
    user_code: str


class DeviceCodePoll(BaseModel):
    device_code: str


@app.post("/api/auth/device/code")
async def start_device_code(body: DeviceCodeStart):
    """
    APK starts a device-code link. Shows user_code; user approves on the web UI
    while signed in with the same Cognito (or local) account.
    """
    user_code = secrets.token_hex(3).upper()  # 6 hex chars
    device_code = secrets.token_urlsafe(24)
    expires_at = datetime.now().timestamp() + 600
    meta = {
        "user_code": user_code,
        "device_code": device_code,
        "device_name": body.device_name,
        "platform": body.platform,
        "expires_at": expires_at,
        "approved": False,
        "owner": None,
        "access_token": None,
        "session_token": None,
        "device_id": None,
    }
    device_link_codes[user_code] = meta
    # Index by device_code too
    device_link_codes[f"dc:{device_code}"] = meta
    ui = os.environ.get("FRONTEND_URL") or os.environ.get("NETLIFY_URL") or ""
    return {
        "user_code": user_code,
        "device_code": device_code,
        "expires_in": 600,
        "interval": 3,
        "verification_uri": f"{ui.rstrip('/')}/account" if ui else "/account",
        "message": "Enter this code on the MobileRun Account page while signed in",
    }


@app.post("/api/auth/device/approve")
async def approve_device_code(
    body: DeviceCodeApprove, auth: Optional[dict] = Depends(optional_verify_token)
):
    """Signed-in user (Mac) approves a phone's device code → phone auto-links."""
    if auth is None:
        raise HTTPException(status_code=401, detail="Sign in to approve a device")
    code = body.user_code.strip().upper()
    meta = device_link_codes.get(code)
    if not meta or datetime.now().timestamp() > meta["expires_at"]:
        raise HTTPException(status_code=400, detail="Invalid or expired code")
    owner = _owner_key(auth)
    device_id = f"device_{secrets.token_hex(8)}"
    session_token = secrets.token_urlsafe(32)
    access = create_access_token(
        {"sub": auth.get("sub") or owner, "email": owner, "device_id": device_id}
    )
    meta["approved"] = True
    meta["owner"] = owner
    meta["access_token"] = access
    meta["session_token"] = session_token
    meta["device_id"] = device_id
    device_sessions[session_token] = {
        "device_id": device_id,
        "name": meta["device_name"],
        "platform": meta["platform"],
        "owner": owner,
        "created_at": datetime.now().isoformat(),
    }
    # Pre-register device row so it appears in UI immediately
    connected_devices[device_id] = {
        "device_id": device_id,
        "name": meta["device_name"],
        "platform": meta["platform"],
        "connected": False,
        "connection_type": "pending",
        "owner": owner,
        "last_seen": datetime.now(),
    }
    return {"ok": True, "device_id": device_id, "owner": owner}


@app.post("/api/auth/device/token")
async def poll_device_code(body: DeviceCodePoll):
    """APK polls until the user approves the code on the web UI."""
    meta = device_link_codes.get(f"dc:{body.device_code}")
    if not meta or datetime.now().timestamp() > meta["expires_at"]:
        raise HTTPException(status_code=400, detail="expired_token")
    if not meta.get("approved"):
        raise HTTPException(status_code=400, detail="authorization_pending")
    return {
        "access_token": meta["access_token"],
        "session_token": meta["session_token"],
        "device_id": meta["device_id"],
        "token_type": "bearer",
        "owner": meta["owner"],
    }


# === Main Endpoints ===


@app.get("/")
async def root():
    """Health check endpoint."""
    return {
        "service": "Mobilerun Backend",
        "version": "1.0.0",
        "status": "running",
        "devices_connected": len(
            [d for d in connected_devices.values() if d.get("connected", False)]
        ),
        "active_runs": len(active_runs),
    }


@app.get("/api/devices", response_model=List[DeviceInfo])
async def list_devices(auth: Optional[dict] = Depends(optional_verify_token)):
    """List devices owned by the signed-in account."""
    devices = []
    for device_id, device_data in connected_devices.items():
        if not _device_visible_to(device_data, auth):
            continue
        devices.append(
            DeviceInfo(
                device_id=device_id,
                name=device_data["name"],
                platform=device_data["platform"],
                connected=device_data.get("connected", False),
                connection_type=device_data.get("connection_type", "unknown"),
                last_seen=device_data.get("last_seen", datetime.now()),
                route=device_data.get("route"),
                latency_ms=device_data.get("latency_ms"),
                permissions=device_data.get("permissions"),
            )
        )
    return devices


@app.get("/api/health")
async def health():
    """Public health check (no auth)."""
    return {
        "status": "ok",
        "service": "mobilerun",
        "step_driven": os.environ.get("STEP_DRIVEN", "false"),
        "use_aws_storage": os.environ.get("USE_AWS_STORAGE", "false"),
        "websocket_api": os.environ.get("WEBSOCKET_API_ENDPOINT", ""),
        "mdns_service": "_mobilerun._tcp",
        "usb_required": False,
    }


def _lan_endpoints(port: Optional[int] = None) -> tuple[str, str]:
    """HTTP + WS URLs for laptop LAN (mDNS / QR)."""
    try:
        from mobilerun.server.mdns import get_lan_ip

        ip = get_lan_ip(os.environ.get("HOST"))
    except Exception:
        ip = "127.0.0.1"
    p = port or int(os.environ.get("PORT", "8000"))
    http = f"http://{ip}:{p}"
    ws = f"ws://{ip}:{p}/api/devices/connect"
    return http, ws


@app.post("/api/devices/pair")
async def initiate_pairing(
    request: PairingRequest, auth: Optional[dict] = Depends(optional_verify_token)
):
    """
    Initiate device pairing. Returns QR with LAN + cloud WebSocket endpoints.
    Phone never needs USB/ADB — it dials out and auto-selects the best route.
    """
    from mobilerun.connectivity.endpoints import build_pairing_url, http_to_ws

    token = secrets.token_urlsafe(32)

    cloud_http = os.environ.get("BACKEND_URL") or os.environ.get("API_URL") or ""
    cloud_ws = os.environ.get("WEBSOCKET_API_ENDPOINT") or ""
    # Local serve: advertise LAN even when BACKEND_URL points at AWS
    lan_http, lan_ws = _lan_endpoints()
    use_aws = os.environ.get("USE_AWS_STORAGE", "false").lower() == "true"
    if use_aws and cloud_http:
        # On Lambda, "LAN" is not meaningful — primary is cloud
        backend_url = cloud_http
        ws_url = cloud_ws or http_to_ws(cloud_http)
        lan_http_out, lan_ws_out = None, None
        cloud_http_out, cloud_ws_out = cloud_http, ws_url
    else:
        backend_url = lan_http
        ws_url = lan_ws
        lan_http_out, lan_ws_out = lan_http, lan_ws
        # Optional cloud fallback baked into the same QR (env override)
        cloud_http_out = cloud_http or os.environ.get("CLOUD_BACKEND_URL") or None
        cloud_ws_out = (
            cloud_ws
            or os.environ.get("CLOUD_WEBSOCKET_URL")
            or (http_to_ws(cloud_http_out) if cloud_http_out else None)
        )

    expires_at = datetime.now().timestamp() + 600
    pairing_data = {
        "token": token,
        "device_name": request.device_name,
        "device_id": request.device_name,
        "platform": request.platform,
        "created_at": datetime.now().isoformat(),
        "expires_at": expires_at,
        "backend_url": backend_url,
        "websocket_url": ws_url,
        "lan_http": lan_http_out,
        "lan_ws": lan_ws_out,
        "cloud_http": cloud_http_out,
        "cloud_ws": cloud_ws_out,
        "owner": _owner_key(auth),
    }

    pairing_tokens[token] = pairing_data

    # Persist for Lambda (memory does not survive across invocations)
    try:
        from storage import save_pairing_token

        save_pairing_token(
            token,
            {
                "device_name": request.device_name,
                "device_id": request.device_name,
                "platform": request.platform,
                "expires_at": expires_at,
                "backend_url": backend_url,
                "cloud_ws": cloud_ws_out,
                "lan_ws": lan_ws_out,
            },
        )
    except Exception as e:
        logger.warning("Could not persist pairing token: %s", e)

    pairing_url = build_pairing_url(
        token=token,
        backend=backend_url,
        ws=ws_url,
        lan_http=lan_http_out,
        lan_ws=lan_ws_out,
        cloud_http=cloud_http_out,
        cloud_ws=cloud_ws_out,
    )

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(pairing_url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    qr_base64 = base64.b64encode(buf.getvalue()).decode()

    return {
        "token": token,
        "qr_code": qr_base64,
        "pairing_url": pairing_url,
        "backend_url": backend_url,
        "websocket_url": ws_url,
        "lan_http": lan_http_out,
        "lan_ws": lan_ws_out,
        "cloud_http": cloud_http_out,
        "cloud_ws": cloud_ws_out,
        "mdns_service": "_mobilerun._tcp",
        "expires_in": 600,
    }


@app.websocket("/api/devices/connect")
async def device_websocket(websocket: WebSocket):
    """
    WebSocket for device connection (outbound from phone — no USB/ADB).
    Auth: Cognito/local JWT (auth_token) OR one-time pairing token OR session_token.
    """
    await websocket.accept()
    device_id = None

    try:
        data = await websocket.receive_json()
        token = data.get("token")
        session_token = data.get("session_token")
        auth_token = data.get("auth_token") or data.get("jwt")
        route = (data.get("route") or "wifi").lower()
        latency_ms = data.get("latency_ms")
        pairing_data = None
        owner = None

        if session_token and session_token in device_sessions:
            sess = device_sessions[session_token]
            device_id = sess["device_id"]
            owner = sess.get("owner")
            pairing_data = {
                "device_name": sess.get("name") or device_id,
                "platform": sess.get("platform", "android"),
                "owner": owner,
            }
        elif auth_token:
            # Same Cognito/local account as the web UI → auto-register device
            try:
                claims = decode_bearer(auth_token)
            except HTTPException as e:
                await websocket.send_json({"error": e.detail})
                await websocket.close()
                return
            owner = _owner_key(claims)
            device_id = data.get("device_id") or f"device_{secrets.token_hex(8)}"
            pairing_data = {
                "device_name": data.get("device_name")
                or data.get("name")
                or "Android",
                "platform": data.get("platform") or "android",
                "owner": owner,
            }
            session_token = secrets.token_urlsafe(32)
            device_sessions[session_token] = {
                "device_id": device_id,
                "name": pairing_data["device_name"],
                "platform": pairing_data["platform"],
                "owner": owner,
                "created_at": datetime.now().isoformat(),
            }
        elif token and token in pairing_tokens:
            pairing_data = pairing_tokens[token]
            if datetime.now().timestamp() > pairing_data["expires_at"]:
                await websocket.send_json({"error": "Token expired"})
                await websocket.close()
                del pairing_tokens[token]
                return
            device_id = data.get("device_id") or f"device_{secrets.token_hex(8)}"
            owner = pairing_data.get("owner")
            del pairing_tokens[token]
            # Issue reconnect session
            session_token = secrets.token_urlsafe(32)
            device_sessions[session_token] = {
                "device_id": device_id,
                "name": pairing_data["device_name"],
                "platform": pairing_data["platform"],
                "owner": owner,
                "created_at": datetime.now().isoformat(),
            }
        else:
            await websocket.send_json({"error": "Invalid or expired token / session"})
            await websocket.close()
            return

        conn_type = route if route in ("lan", "cloud", "discovered") else "wifi"
        connected_devices[device_id] = {
            "device_id": device_id,
            "name": pairing_data["device_name"],
            "platform": pairing_data["platform"],
            "connected": True,
            "connection_type": conn_type,
            "route": conn_type,
            "latency_ms": latency_ms,
            "owner": owner or pairing_data.get("owner"),
            "last_seen": datetime.now(),
        }

        device_websockets[device_id] = websocket

        await websocket.send_json(
            {
                "status": "connected",
                "device_id": device_id,
                "session_token": session_token,
                "route": conn_type,
                "latency_ms": latency_ms,
            }
        )

        logger.info(
            "Device %s connected via %s (latency=%s)",
            device_id,
            conn_type,
            latency_ms,
        )

        while True:
            try:
                message = await websocket.receive_json()
                await handle_device_message(device_id, message)
            except WebSocketDisconnect:
                break

    except Exception as e:
        logger.error(f"Device connection error: {e}")
    finally:
        if device_id:
            if device_id in connected_devices:
                connected_devices[device_id]["connected"] = False
            if device_id in device_websockets:
                del device_websockets[device_id]
            logger.info(f"Device {device_id} disconnected")


async def _send_to_device(device_id: str, payload: dict) -> bool:
    ws = device_websockets.get(device_id)
    if not ws:
        return False
    try:
        await ws.send_json(payload)
        return True
    except Exception as e:
        logger.warning("send to device %s failed: %s", device_id, e)
        return False


async def handle_device_message(device_id: str, message: dict):
    """Handle messages from connected device."""
    from backend.live_hub import broadcast_to_ui, relay_frame, update_agent_state

    msg_type = message.get("type")
    connected_devices.setdefault(device_id, {})["last_seen"] = datetime.now()

    if msg_type == "heartbeat":
        ws = device_websockets.get(device_id)
        if ws:
            await ws.send_json(
                {
                    "type": "heartbeat_ack",
                    "server_ts": int(datetime.now().timestamp() * 1000),
                }
            )

    elif msg_type == "connection_status":
        # Phone reports active route + measured RTT
        dev = connected_devices.setdefault(device_id, {})
        if message.get("route"):
            route = str(message["route"]).lower()
            dev["route"] = route
            dev["connection_type"] = route
        if message.get("latency_ms") is not None:
            try:
                dev["latency_ms"] = float(message["latency_ms"])
            except (TypeError, ValueError):
                pass
        await broadcast_to_ui(
            device_id,
            {
                "type": "connection_status",
                "device_id": device_id,
                "route": dev.get("route"),
                "latency_ms": dev.get("latency_ms"),
            },
        )

    elif msg_type == "permission_status":
        # APK first-run / resume checklist → visible on hosted Devices page
        keys = (
            "accessibility",
            "notifications",
            "media_projection",
            "battery_optimization",
            "overlay",
            "query_packages",
            "foreground_service",
            "updated_at",
        )
        perms = {k: message.get(k) for k in keys if k in message}
        dev = connected_devices.setdefault(device_id, {})
        dev["permissions"] = perms
        await broadcast_to_ui(
            device_id,
            {
                "type": "permission_status",
                "device_id": device_id,
                "permissions": perms,
            },
        )

    elif msg_type == "task_update":
        task_id = message.get("task_id")
        if task_id in active_runs:
            active_runs[task_id].update(message.get("update", {}))
        await broadcast_to_ui(
            device_id,
            {"type": "task_update", "device_id": device_id, **message},
        )

    elif msg_type == "frame":
        # Ephemeral relay only — never store frames (bandwidth/cost).
        await relay_frame(
            device_id,
            {
                "mime": message.get("mime", "image/jpeg"),
                "width": message.get("width"),
                "height": message.get("height"),
                "seq": message.get("seq"),
                "ts": message.get("ts"),
                "data": message.get("data"),
            },
        )

    elif msg_type == "agent_event":
        state = update_agent_state(
            device_id,
            {
                "current_app": message.get("current_app"),
                "step": message.get("step"),
                "action": message.get("action"),
                "log": message.get("log"),
            },
        )
        await broadcast_to_ui(
            device_id,
            {"type": "agent_event", "device_id": device_id, "state": state},
        )

    elif msg_type in ("screenshot", "response"):
        # Optional one-shot screenshot / command response — fan out if UI cares
        await broadcast_to_ui(
            device_id, {"type": msg_type, "device_id": device_id, **message}
        )


@app.post("/api/tasks", response_model=TaskStatus)
async def submit_task(
    request: TaskRequest, auth: Optional[dict] = Depends(optional_verify_token)
):
    """Submit a new automation task to a device."""
    if request.device_id not in connected_devices:
        raise HTTPException(status_code=404, detail="Device not found")

    if not connected_devices[request.device_id].get("connected", False):
        raise HTTPException(status_code=400, detail="Device not connected")

    task_id = f"task_{secrets.token_hex(8)}"

    mode = (request.mode or "normal").lower()
    if mode not in ("normal", "dating", "social"):
        raise HTTPException(
            status_code=400, detail="mode must be 'normal', 'dating', or 'social'"
        )
    speed = (request.speed_preset or "balanced").lower()
    if speed not in ("fast", "balanced", "careful"):
        raise HTTPException(
            status_code=400, detail="speed_preset must be fast|balanced|careful"
        )

    task = {
        "task_id": task_id,
        "device_id": request.device_id,
        "instruction": request.instruction,
        "status": "pending",
        "current_step": 0,
        "max_steps": request.max_steps,
        "reasoning": request.reasoning,
        "vision": request.vision,
        "mode": mode,
        "speed_preset": speed,
        "result": None,
        "error": None,
        "started_at": datetime.now(),
        "completed_at": None,
    }

    active_runs[task_id] = task

    # Send task to device via WebSocket
    ws = device_websockets.get(request.device_id)
    if ws:
        try:
            await ws.send_json(
                {
                    "type": "run_task",
                    "task_id": task_id,
                    "instruction": request.instruction,
                    "max_steps": request.max_steps,
                    "reasoning": request.reasoning,
                    "vision": request.vision,
                    "mode": mode,
                    "speed_preset": speed,
                }
            )
            task["status"] = "running"
        except Exception as e:
            logger.error(f"Failed to send task to device: {e}")
            task["status"] = "failed"
            task["error"] = "Failed to communicate with device"

    return TaskStatus(**task)


@app.get("/api/tasks/{task_id}", response_model=TaskStatus)
async def get_task_status(
    task_id: str, auth: Optional[dict] = Depends(optional_verify_token)
):
    """Get status of a specific task."""
    if task_id in active_runs:
        return TaskStatus(**active_runs[task_id])

    for run in run_history:
        if run["task_id"] == task_id:
            return TaskStatus(**run)

    raise HTTPException(status_code=404, detail="Task not found")


@app.get("/api/tasks", response_model=List[TaskStatus])
async def list_tasks(
    limit: int = 50, auth: Optional[dict] = Depends(optional_verify_token)
):
    """List recent tasks."""
    tasks = list(active_runs.values()) + run_history
    tasks.sort(key=lambda t: t["started_at"], reverse=True)
    return [TaskStatus(**t) for t in tasks[:limit]]


# Self-hosted LLM providers (Mac pays AWS + LLM tokens only).
SUPPORTED_LLM_PROVIDERS = ("gemini", "openai", "anthropic", "xai")
DEFAULT_LLM_MODELS = {
    "gemini": "gemini-3.8-flash",
    "openai": "gpt-6-astra",
    "anthropic": "claude-sonnet-5",
    # Current xAI docs flagship; override with LLM_MODEL / UI model field.
    "xai": "grok-4.7",
}
LLM_ENV_KEY_MAP = {
    "gemini": "GOOGLE_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "xai": "XAI_API_KEY",
}


@app.get("/api/config/llm")
async def get_llm_config(auth: Optional[dict] = Depends(optional_verify_token)):
    """Get current LLM configuration."""
    provider = os.environ.get("LLM_PROVIDER", "gemini")
    default_model = DEFAULT_LLM_MODELS.get(provider, DEFAULT_LLM_MODELS["gemini"])
    return {
        "provider": provider,
        "model": os.environ.get("LLM_MODEL", default_model),
        "temperature": float(os.environ.get("LLM_TEMPERATURE", "0.7")),
        "max_tokens": int(os.environ.get("LLM_MAX_TOKENS", "2048")),
        "supported_providers": list(SUPPORTED_LLM_PROVIDERS),
        "default_models": dict(DEFAULT_LLM_MODELS),
        "xai_api_base": "https://api.x.ai/v1",
    }


@app.post("/api/config/llm")
async def update_llm_config(
    config: LLMConfig, auth: Optional[dict] = Depends(optional_verify_token)
):
    """Update LLM configuration."""
    provider = config.provider.strip().lower()
    if provider not in SUPPORTED_LLM_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Provider must be one of: {', '.join(SUPPORTED_LLM_PROVIDERS)}",
        )

    model = (config.model or "").strip() or DEFAULT_LLM_MODELS[provider]

    # Save to environment (Lambda environment variables managed via CDK)
    os.environ["LLM_PROVIDER"] = provider
    os.environ["LLM_MODEL"] = model
    os.environ["LLM_TEMPERATURE"] = str(config.temperature)
    os.environ["LLM_MAX_TOKENS"] = str(config.max_tokens)

    if config.api_key:
        os.environ[LLM_ENV_KEY_MAP[provider]] = config.api_key

    return {
        "status": "success",
        "provider": provider,
        "model": model,
    }


@app.get("/api/releases/latest")
async def get_latest_release():
    """Get latest APK release info with QR code."""
    repo = "MacAndersonUche/mobilerun"
    latest_url = f"https://github.com/{repo}/releases/latest/download/mobilerun.apk"

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(latest_url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    qr_base64 = base64.b64encode(buf.getvalue()).decode()

    return {
        "version": "latest",
        "apk_url": latest_url,
        "qr_code": qr_base64,
        "release_notes": "Latest build from main branch",
    }


# === Dating Mode API ===

dating_mode_state = {
    "running": False,
    "paused": False,
    "current_app": None,
    "review_queue": [],
    "speed_preset": "balanced",
}

social_mode_state = {
    "running": False,
    "paused": False,
    "current_app": None,
    "speed_preset": "balanced",
    "unread": {"total_unread": 0, "by_app": {}},
}

# Global agent mode selection (UI / CLI / chat)
agent_mode_state = {
    "mode": "normal",  # normal | dating | social
    "speed_preset": "balanced",  # fast | balanced | careful
}

_needs_you_queue = None


def get_needs_you_queue():
    """Shared Needs-you queue (Social + Dating)."""
    global _needs_you_queue
    if _needs_you_queue is None:
        from mobilerun.needs_you.queue import NeedsYouQueue

        path = Path.home() / ".mobilerun" / "needs_you.json"
        if os.environ.get("MOBILERUN_DATA"):
            path = Path(os.environ["MOBILERUN_DATA"]) / "needs_you.json"
        _needs_you_queue = NeedsYouQueue(persist_path=path)
    return _needs_you_queue


class DatingModeConfig(BaseModel):
    """Dating mode configuration."""

    enabled_apps: List[str]
    round_robin: bool = True
    review_before_send: bool = True
    persona_prompt: str = ""
    active_hours_start: str = "09:00"
    active_hours_end: str = "23:00"
    min_total_messages_per_day: int = 100
    max_total_messages_per_day: int = 500
    sequential_messaging: bool = True
    speed_preset: str = "balanced"


class AgentModeConfig(BaseModel):
    mode: str = "normal"
    speed_preset: str = "balanced"


class DatingMessage(BaseModel):
    """Dating message for review."""

    id: str
    app_name: str
    package_name: str
    conversation_id: str
    profile_name: str
    message: str
    is_opener: bool = False


class SocialConfigUpdate(BaseModel):
    enabled_apps: Optional[List[str]] = None
    speed_preset: str = "balanced"
    tone_prompt: Optional[str] = None
    signature_enabled: bool = True
    signature_text: str = "— from MacAI"
    per_app_signature: Optional[Dict[str, bool]] = None
    always_ask_new_contacts: bool = True
    email_notify: bool = False
    email_to: str = "macandersonuche@yahoo.com"


class SocialDraftRequest(BaseModel):
    app_name: str
    package_name: str
    conversation_id: str
    contact_name: str
    draft_reply: str
    inbound_preview: str = ""
    confidence: float = 0.8
    is_new_contact: bool = False


class NeedsYouEdit(BaseModel):
    draft_reply: Optional[str] = None


@app.get("/api/mode")
async def get_agent_mode(auth: Optional[dict] = Depends(optional_verify_token)):
    """Current interaction mode + humanizer speed preset."""
    from mobilerun.agent.humanizer import describe_presets

    return {
        **agent_mode_state,
        "presets": describe_presets(),
        "needs_you_badge": get_needs_you_queue().pending_count(),
        "modes": {
            "normal": "General-purpose phone agent (open apps, navigate, type, multi-step)",
            "dating": "Dating apps: swipes, openers, replies with human-like pacing",
            "social": "WhatsApp/Messenger/X/Snapchat/Instagram — unread + replies in Mac's tone",
        },
    }


@app.post("/api/mode")
async def set_agent_mode(
    body: AgentModeConfig, auth: Optional[dict] = Depends(optional_verify_token)
):
    """Select Normal / Dating / Social and Fast / Balanced / Careful pacing."""
    mode = (body.mode or "normal").lower()
    speed = (body.speed_preset or "balanced").lower()
    if mode not in ("normal", "dating", "social"):
        raise HTTPException(
            status_code=400, detail="mode must be 'normal', 'dating', or 'social'"
        )
    if speed not in ("fast", "balanced", "careful"):
        raise HTTPException(
            status_code=400, detail="speed_preset must be fast|balanced|careful"
        )
    agent_mode_state["mode"] = mode
    agent_mode_state["speed_preset"] = speed
    dating_mode_state["speed_preset"] = speed
    social_mode_state["speed_preset"] = speed
    return {"status": "ok", **agent_mode_state}


@app.get("/api/dating/config")
async def get_dating_config(auth: Optional[dict] = Depends(optional_verify_token)):
    """Get dating mode configuration."""
    from mobilerun.dating.config import DatingModeConfig as ConfigModel

    config = ConfigModel()
    return {
        "apps": [
            {
                "name": app.name,
                "package_name": app.package_name,
                "enabled": app.enabled,
                "daily_swipe_cap": app.daily_swipe_cap,
                "daily_reply_cap": app.daily_reply_cap,
                "daily_opener_target_min": app.daily_opener_target_min,
                "daily_opener_target_max": app.daily_opener_target_max,
            }
            for app in config.apps
        ],
        "round_robin": config.round_robin,
        "review_before_send": config.review_before_send,
        "sequential_messaging": config.sequential_messaging,
        "persona_prompt": config.persona_prompt,
        "active_hours_start": config.active_hours_start.isoformat(),
        "active_hours_end": config.active_hours_end.isoformat(),
        "min_total_messages_per_day": config.min_total_messages_per_day,
        "max_total_messages_per_day": config.max_total_messages_per_day,
        "speed_preset": getattr(config, "speed_preset", None)
        or dating_mode_state.get("speed_preset", "balanced"),
    }


@app.post("/api/dating/config")
async def update_dating_config(
    config: DatingModeConfig, auth: Optional[dict] = Depends(optional_verify_token)
):
    """Update dating mode configuration."""
    speed = (config.speed_preset or "balanced").lower()
    if speed not in ("fast", "balanced", "careful"):
        raise HTTPException(
            status_code=400, detail="speed_preset must be fast|balanced|careful"
        )
    dating_mode_state["speed_preset"] = speed
    agent_mode_state["speed_preset"] = speed
    agent_mode_state["mode"] = "dating"
    return {"status": "success", "config": config.dict()}


@app.get("/api/dating/stats")
async def get_dating_stats(auth: Optional[dict] = Depends(optional_verify_token)):
    """Get dating mode statistics."""
    from mobilerun.dating.stats import DatingStats

    stats_file = Path.home() / ".mobilerun" / "dating_stats.json"
    stats = DatingStats.load(stats_file)

    return stats.get_summary()


@app.post("/api/dating/start")
async def start_dating_mode(
    auth: Optional[dict] = Depends(optional_verify_token),
    device_id: str = "default",
    dry_run: bool = False,
):
    """
    Start dating mode as a step-driven cloud job (EventBridge ticks).
    Safe for Lambda — does not hold a long loop in one invocation.
    """
    if dating_mode_state["running"]:
        raise HTTPException(status_code=400, detail="Dating mode already running")

    dating_mode_state["running"] = True
    dating_mode_state["paused"] = False

    job_id = f"dating_{secrets.token_hex(8)}"
    dating_mode_state["job_id"] = job_id
    job = {
        "job_id": job_id,
        "kind": "dating",
        "status": "running",
        "device_id": device_id,
        "dry_run": dry_run,
        "created_at": int(datetime.now().timestamp()),
        "next_run_at": int(datetime.now().timestamp()),
        "speed_preset": dating_mode_state.get("speed_preset")
        or agent_mode_state.get("speed_preset", "balanced"),
        "caps": {
            "opener_target": secrets.randbelow(51) + 50,  # 50-100
            "global_message_max": secrets.randbelow(401) + 100,  # 100-500
            "swipe_cap": 50,
            "reply_cap": 50,
        },
        "state": {
            "openers_sent": 0,
            "replies_sent": 0,
            "swipes_done": 0,
            "steps": 0,
        },
        "ttl": int(datetime.now().timestamp()) + 7 * 86400,
    }
    agent_mode_state["mode"] = "dating"
    try:
        from storage import put_job

        put_job(job)
        # Kick first step immediately if step worker ARN available
        step_arn = os.environ.get("STEP_WORKER_ARN")
        if step_arn and os.environ.get("USE_AWS_STORAGE") == "true":
            import boto3

            boto3.client("lambda").invoke(
                FunctionName=step_arn,
                InvocationType="Event",
                Payload=json.dumps({"job_id": job_id}).encode(),
            )
    except Exception as e:
        logger.warning("Could not persist dating job (local mode ok): %s", e)

    return {"status": "started", "state": dating_mode_state, "job": job}


@app.post("/api/dating/stop")
async def stop_dating_mode(auth: Optional[dict] = Depends(optional_verify_token)):
    """Stop dating mode / mark cloud job completed."""
    dating_mode_state["running"] = False
    dating_mode_state["paused"] = False
    dating_mode_state["current_app"] = None
    job_id = dating_mode_state.pop("job_id", None)
    if job_id:
        try:
            from storage import get_job, put_job

            job = get_job(job_id)
            if job:
                job["status"] = "stopped"
                put_job(job)
        except Exception as e:
            logger.warning("Could not stop job: %s", e)

    return {"status": "stopped", "state": dating_mode_state}


@app.post("/api/dating/pause")
async def pause_dating_mode(auth: Optional[dict] = Depends(optional_verify_token)):
    """Pause dating mode."""
    if not dating_mode_state["running"]:
        raise HTTPException(status_code=400, detail="Dating mode not running")

    dating_mode_state["paused"] = not dating_mode_state["paused"]

    return {
        "status": "paused" if dating_mode_state["paused"] else "resumed",
        "state": dating_mode_state,
    }


@app.get("/api/dating/status")
async def get_dating_status(auth: Optional[dict] = Depends(optional_verify_token)):
    """Get dating mode status."""
    return dating_mode_state


@app.get("/api/dating/review-queue")
async def get_review_queue(auth: Optional[dict] = Depends(optional_verify_token)):
    """Get messages in review queue (also mirrored in /api/needs-you)."""
    return {
        "messages": dating_mode_state["review_queue"],
        "needs_you": [
            i.to_dict() for i in get_needs_you_queue().list_pending(source="dating")
        ],
    }


@app.post("/api/dating/review/{message_id}/approve")
async def approve_message(
    message_id: str, auth: Optional[dict] = Depends(optional_verify_token)
):
    """Approve a message for sending."""
    dating_mode_state["review_queue"] = [
        msg for msg in dating_mode_state["review_queue"] if msg["id"] != message_id
    ]
    get_needs_you_queue().approve(message_id)
    return {"status": "approved", "message_id": message_id}


@app.post("/api/dating/review/{message_id}/reject")
async def reject_message(
    message_id: str, auth: Optional[dict] = Depends(optional_verify_token)
):
    """Reject a message."""
    dating_mode_state["review_queue"] = [
        msg for msg in dating_mode_state["review_queue"] if msg["id"] != message_id
    ]
    get_needs_you_queue().reject(message_id)
    return {"status": "rejected", "message_id": message_id}


@app.post("/api/dating/review/{message_id}/edit")
async def edit_message(
    message_id: str,
    message: DatingMessage,
    auth: Optional[dict] = Depends(optional_verify_token),
):
    """Edit a message in review queue."""
    for i, msg in enumerate(dating_mode_state["review_queue"]):
        if msg["id"] == message_id:
            dating_mode_state["review_queue"][i] = message.dict()
            get_needs_you_queue().edit(message_id, message.message)
            return {"status": "updated", "message": message.dict()}

    # May only exist in Needs-you (synced dating item)
    item = get_needs_you_queue().edit(message_id, message.message)
    if item:
        return {"status": "updated", "message": item.to_dict()}

    raise HTTPException(status_code=404, detail="Message not found")


@app.post("/api/dating/review")
async def enqueue_dating_review(
    message: DatingMessage, auth: Optional[dict] = Depends(optional_verify_token)
):
    """Enqueue a dating draft into review + shared Needs-you queue."""
    payload = message.dict() if hasattr(message, "dict") else message.model_dump()
    dating_mode_state["review_queue"].append(payload)
    q = get_needs_you_queue()
    if q.get(message.id) is None:
        q.add(
            source="dating",
            app_name=message.app_name,
            package_name=message.package_name,
            conversation_id=message.conversation_id,
            contact_name=message.profile_name,
            inbound_preview="",
            draft_reply=message.message,
            reasons=["dating_review"] + (["opener"] if message.is_opener else []),
            confidence=0.5,
            meta={"is_opener": message.is_opener},
            item_id=message.id,
        )
    return {
        "status": "queued",
        "message": payload,
        "needs_you_id": message.id,
        "badge": q.pending_count(),
    }


# === Social mode + Needs-you ===

_social_config_store: Dict[str, Any] = {}


def _social_config():
    from mobilerun.needs_you.escalation import EscalationRules
    from mobilerun.social.config import SocialModeConfig
    from mobilerun.social.signature import SignatureConfig

    if _social_config_store.get("config") is None:
        _social_config_store["config"] = SocialModeConfig()
    cfg: SocialModeConfig = _social_config_store["config"]
    # Keep type imports happy for readers
    _ = (EscalationRules, SignatureConfig)
    return cfg


@app.get("/api/social/config")
async def get_social_config(auth: Optional[dict] = Depends(optional_verify_token)):
    cfg = _social_config()
    return {
        "apps": [
            {
                "name": a.name,
                "package_name": a.package_name,
                "enabled": a.enabled,
                "signature_enabled": a.signature_enabled,
            }
            for a in cfg.apps
        ],
        "speed_preset": cfg.speed_preset,
        "tone_prompt": cfg.tone_prompt,
        "signature": cfg.signature.to_dict(),
        "escalation": {
            "always_ask_new_contacts": cfg.escalation.always_ask_new_contacts,
            "always_ask_money": cfg.escalation.always_ask_money,
            "always_ask_commitments": cfg.escalation.always_ask_commitments,
            "always_ask_personal_info": cfg.escalation.always_ask_personal_info,
            "min_confidence_to_autosend": cfg.escalation.min_confidence_to_autosend,
            "trusted_contacts": cfg.escalation.trusted_contacts,
        },
        "email_notify": cfg.email_notify,
        "email_to": cfg.email_to,
    }


@app.post("/api/social/config")
async def update_social_config(
    body: SocialConfigUpdate, auth: Optional[dict] = Depends(optional_verify_token)
):
    cfg = _social_config()
    if body.enabled_apps is not None:
        enabled = set(body.enabled_apps)
        for app in cfg.apps:
            app.enabled = app.package_name in enabled
    cfg.speed_preset = body.speed_preset
    if body.tone_prompt is not None:
        cfg.tone_prompt = body.tone_prompt
    cfg.signature.enabled_global = body.signature_enabled
    cfg.signature.text = body.signature_text or cfg.signature.text
    if body.per_app_signature:
        cfg.signature.per_app.update(body.per_app_signature)
        for app in cfg.apps:
            if app.package_name in body.per_app_signature:
                app.signature_enabled = body.per_app_signature[app.package_name]
    cfg.escalation.always_ask_new_contacts = body.always_ask_new_contacts
    cfg.email_notify = body.email_notify
    cfg.email_to = body.email_to
    social_mode_state["speed_preset"] = body.speed_preset
    agent_mode_state["speed_preset"] = body.speed_preset
    agent_mode_state["mode"] = "social"
    return {"status": "ok", "config": await get_social_config(auth)}


@app.get("/api/social/status")
async def get_social_status(auth: Optional[dict] = Depends(optional_verify_token)):
    return {
        **social_mode_state,
        "needs_you_badge": get_needs_you_queue().pending_count(),
    }


@app.post("/api/social/start")
async def start_social_mode(auth: Optional[dict] = Depends(optional_verify_token)):
    social_mode_state["running"] = True
    social_mode_state["paused"] = False
    agent_mode_state["mode"] = "social"
    return {"status": "started", "state": social_mode_state}


@app.post("/api/social/stop")
async def stop_social_mode(auth: Optional[dict] = Depends(optional_verify_token)):
    social_mode_state["running"] = False
    social_mode_state["paused"] = False
    return {"status": "stopped", "state": social_mode_state}


@app.post("/api/social/pause")
async def pause_social_mode(auth: Optional[dict] = Depends(optional_verify_token)):
    social_mode_state["paused"] = not social_mode_state.get("paused", False)
    return {
        "status": "paused" if social_mode_state["paused"] else "resumed",
        "state": social_mode_state,
    }


@app.post("/api/social/unread")
async def report_social_unreads(
    body: Dict[str, Any], auth: Optional[dict] = Depends(optional_verify_token)
):
    from mobilerun.social.agent import summarize_unreads

    threads = body.get("threads") or []
    summary = summarize_unreads(threads)
    social_mode_state["unread"] = summary
    return summary


@app.post("/api/social/draft")
async def social_prepare_draft(
    body: SocialDraftRequest, auth: Optional[dict] = Depends(optional_verify_token)
):
    """Prepare outbound reply: signature + escalation → Needs-you or auto-ok."""
    from mobilerun.needs_you.notify import notify_needs_you
    from mobilerun.social.agent import prepare_outbound

    cfg = _social_config()
    q = get_needs_you_queue()
    decision = prepare_outbound(
        draft_reply=body.draft_reply,
        config=cfg,
        queue=q,
        app_name=body.app_name,
        package_name=body.package_name,
        conversation_id=body.conversation_id,
        contact_name=body.contact_name,
        inbound_preview=body.inbound_preview,
        confidence=body.confidence,
        is_new_contact=body.is_new_contact,
    )
    notify_result = {}
    if decision.needs_you and decision.needs_you_id:
        item = q.get(decision.needs_you_id)
        if item:

            async def _broadcast(did, payload):
                from backend.live_hub import broadcast_to_ui

                await broadcast_to_ui(did if did != "all" else "", payload)

            # Notify all connected devices + any UI subscribers
            for did in list(connected_devices.keys()) or [""]:
                notify_result = await notify_needs_you(
                    item,
                    badge_count=q.pending_count(),
                    broadcast_ui=_broadcast,
                    send_to_device=_send_to_device if did else None,
                    device_id=did or None,
                    email_enabled=cfg.email_notify,
                    email_to=cfg.email_to,
                )
    return {
        **decision.to_dict(),
        "badge": q.pending_count(),
        "notify": notify_result,
        "speed_preset": cfg.speed_preset,
    }


@app.get("/api/needs-you")
async def list_needs_you(
    source: Optional[str] = None,
    auth: Optional[dict] = Depends(optional_verify_token),
):
    q = get_needs_you_queue()
    pending = q.list_pending(source=source)
    return {
        "badge": q.pending_count(),
        "items": [i.to_dict() for i in pending],
        "all": q.to_list(),
    }


@app.post("/api/needs-you/{item_id}/approve")
async def needs_you_approve(
    item_id: str,
    body: NeedsYouEdit = NeedsYouEdit(),
    auth: Optional[dict] = Depends(optional_verify_token),
):
    item = get_needs_you_queue().approve(item_id, edited_reply=body.draft_reply)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    # Keep dating legacy queue in sync
    dating_mode_state["review_queue"] = [
        m for m in dating_mode_state["review_queue"] if m.get("id") != item_id
    ]
    return {
        "status": "approved",
        "item": item.to_dict(),
        "badge": get_needs_you_queue().pending_count(),
    }


@app.post("/api/needs-you/{item_id}/reject")
async def needs_you_reject(
    item_id: str, auth: Optional[dict] = Depends(optional_verify_token)
):
    item = get_needs_you_queue().reject(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    dating_mode_state["review_queue"] = [
        m for m in dating_mode_state["review_queue"] if m.get("id") != item_id
    ]
    return {
        "status": "rejected",
        "item": item.to_dict(),
        "badge": get_needs_you_queue().pending_count(),
    }


@app.post("/api/needs-you/{item_id}/edit")
async def needs_you_edit(
    item_id: str,
    body: NeedsYouEdit,
    auth: Optional[dict] = Depends(optional_verify_token),
):
    if body.draft_reply is None:
        raise HTTPException(status_code=400, detail="draft_reply required")
    item = get_needs_you_queue().edit(item_id, body.draft_reply)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    for m in dating_mode_state["review_queue"]:
        if m.get("id") == item_id:
            m["message"] = body.draft_reply
    return {"status": "updated", "item": item.to_dict()}


# === Live view (UI WebSocket) + chat agent ===


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    device_id: Optional[str] = None
    # "pc" = local serve backend; "hosted" = AWS (UI points URL accordingly)
    target: str = "pc"
    confirmed: bool = False


class InjectFrameRequest(BaseModel):
    device_id: str
    data: str  # base64 JPEG
    mime: str = "image/jpeg"
    width: int = 540
    height: int = 960
    seq: int = 1


@app.websocket("/api/ui/connect")
async def ui_websocket(websocket: WebSocket):
    """
    Browser live-view client.
    Frames/agent_events are pushed as JSON and never stored.
    Subscribe starts MediaProjection stream on the phone; unsubscribe stops it.
    """
    from backend.live_hub import (
        agent_state,
        notify_stream_control,
        stream_wanted,
        subscribe_ui,
        unsubscribe_ui,
    )

    await websocket.accept()
    device_id: Optional[str] = None
    try:
        while True:
            msg = await websocket.receive_json()
            mtype = msg.get("type")
            if mtype == "subscribe":
                device_id = msg.get("device_id")
                if not device_id:
                    await websocket.send_json(
                        {"type": "error", "detail": "device_id required"}
                    )
                    continue
                await subscribe_ui(websocket, device_id)
                await websocket.send_json(
                    {
                        "type": "subscribed",
                        "device_id": device_id,
                        "state": agent_state.get(device_id, {}),
                    }
                )
                fps = int(msg.get("fps", 3))
                quality = int(msg.get("quality", 45))
                await notify_stream_control(
                    _send_to_device, device_id, "start", fps=fps, quality=quality
                )
            elif mtype == "unsubscribe":
                await unsubscribe_ui(websocket)
                if device_id and not stream_wanted.get(device_id):
                    await notify_stream_control(_send_to_device, device_id, "stop")
                device_id = None
            elif mtype == "input":
                did = msg.get("device_id") or device_id
                action = msg.get("action")
                if not did or action not in ("tap", "swipe"):
                    continue
                params = {
                    k: v
                    for k, v in msg.items()
                    if k not in ("type", "device_id", "action")
                }
                await _send_to_device(
                    did,
                    {
                        "type": "command",
                        "command": action,
                        "request_id": f"ui_{secrets.token_hex(4)}",
                        "params": params,
                    },
                )
            elif mtype == "task_control":
                did = msg.get("device_id") or device_id
                if did:
                    await _send_to_device(
                        did,
                        {
                            "type": "task_control",
                            "action": msg.get("action"),
                            "task_id": msg.get("task_id"),
                        },
                    )
            elif mtype == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        from backend.live_hub import stream_wanted as sw

        await unsubscribe_ui(websocket)
        if device_id and not sw.get(device_id):
            await notify_stream_control(_send_to_device, device_id, "stop")


@app.post("/api/live/inject-frame")
async def inject_frame(
    body: InjectFrameRequest, auth: Optional[dict] = Depends(optional_verify_token)
):
    """E2E/test helper: inject a fake JPEG frame as if from the phone."""
    from backend.live_hub import relay_frame

    sent = await relay_frame(
        body.device_id,
        {
            "mime": body.mime,
            "width": body.width,
            "height": body.height,
            "seq": body.seq,
            "ts": datetime.now().timestamp(),
            "data": body.data,
        },
    )
    return {"relayed": sent, "device_id": body.device_id}


@app.get("/api/live/state/{device_id}")
async def live_state(
    device_id: str, auth: Optional[dict] = Depends(optional_verify_token)
):
    from backend.live_hub import agent_state, subscribers_for, stream_wanted

    return {
        "device_id": device_id,
        "subscribers": len(subscribers_for(device_id)),
        "stream_wanted": bool(stream_wanted.get(device_id)),
        "state": agent_state.get(device_id, {}),
    }


@app.post("/api/chat")
async def chat_endpoint(
    body: ChatRequest, auth: Optional[dict] = Depends(optional_verify_token)
):
    """AI chat agent — answers + turns messages into tasks/dating commands."""
    from backend.chat_agent import handle_chat

    target = (body.target or "pc").lower()
    if target not in ("pc", "hosted"):
        raise HTTPException(status_code=400, detail="target must be 'pc' or 'hosted'")

    async def execute(intent: str, params: Dict[str, Any]) -> Dict[str, Any]:
        did = params.get("device_id") or body.device_id
        if intent == "device_info":
            devices = [
                {
                    "device_id": d,
                    "connected": v.get("connected"),
                    "name": v.get("name"),
                    "platform": v.get("platform"),
                }
                for d, v in connected_devices.items()
            ]
            return {"message": f"{len(devices)} device(s)", "devices": devices}
        if intent == "dating_stats":
            try:
                from mobilerun.dating.stats import DatingStats

                stats_file = Path.home() / ".mobilerun" / "dating_stats.json"
                stats = DatingStats.load(stats_file).get_summary()
                return {"message": "Dating stats", "stats": stats}
            except Exception as e:
                return {"message": f"Stats unavailable: {e}", "stats": {}}
        if intent == "needs_you_list":
            items = get_needs_you_queue().list_pending()
            return {
                "message": f"{len(items)} item(s) need you",
                "badge": len(items),
                "items": [i.to_dict() for i in items],
            }
        if intent == "social_unreads":
            unread = social_mode_state.get("unread") or {}
            return {
                "message": f"Unread total: {unread.get('total_unread', 0)}",
                "unread": unread,
            }
        if intent == "dating_start":
            dating_mode_state["running"] = True
            dating_mode_state["paused"] = False
            return {
                "message": (
                    f"Dating mode start requested (dry_run={params.get('dry_run')})"
                ),
                "dry_run": params.get("dry_run", False),
                "device_id": did,
            }
        if intent == "dating_stop":
            dating_mode_state["running"] = False
            dating_mode_state["paused"] = False
            return {"message": "Dating mode stopped"}
        if intent == "dating_pause":
            dating_mode_state["paused"] = not dating_mode_state.get("paused", False)
            return {
                "message": "paused" if dating_mode_state["paused"] else "resumed",
                "state": dating_mode_state,
            }
        if intent in ("task_stop", "task_pause"):
            if did:
                await _send_to_device(
                    did, {"type": "task_control", "action": intent.split("_")[1]}
                )
            return {"message": f"Task {intent} sent", "device_id": did}
        if intent == "set_mode":
            mode = (
                params.get("mode") or agent_mode_state.get("mode", "normal")
            ).lower()
            speed = (
                params.get("speed_preset")
                or agent_mode_state.get("speed_preset", "balanced")
            ).lower()
            await set_agent_mode(
                AgentModeConfig(mode=mode, speed_preset=speed), auth=None
            )
            return {
                "message": f"Mode set to {mode} · speed {speed}",
                **agent_mode_state,
            }
        if intent == "run_task":
            instruction = params.get("instruction") or ""
            if not did:
                return {"message": "No device_id — pair a phone first"}
            mode = params.get("mode") or agent_mode_state.get("mode", "normal")
            speed = params.get("speed_preset") or agent_mode_state.get(
                "speed_preset", "balanced"
            )
            if did not in connected_devices or not connected_devices[did].get(
                "connected"
            ):
                return {
                    "message": f"Queued task on {did}: {instruction}",
                    "queued": True,
                    "instruction": instruction,
                    "mode": mode,
                    "speed_preset": speed,
                }
            task = await submit_task(
                TaskRequest(
                    device_id=did,
                    instruction=instruction,
                    mode=mode,
                    speed_preset=speed,
                ),
                auth=None,
            )
            dumped = task.model_dump() if hasattr(task, "model_dump") else task.dict()
            return {
                "message": f"Started task {task.task_id}: {instruction}",
                "task": dumped,
            }
        return {"message": f"Unhandled intent {intent}"}

    context = {
        "devices": list(connected_devices.keys()),
        "dating_running": dating_mode_state.get("running"),
        "mode": agent_mode_state.get("mode"),
        "speed_preset": agent_mode_state.get("speed_preset"),
        "provider": os.environ.get("LLM_PROVIDER", "gemini"),
        "target": target,
    }
    return await handle_chat(
        message=body.message,
        session_id=body.session_id,
        device_id=body.device_id,
        target=target,
        confirmed=body.confirmed,
        context=context,
        execute=execute,
    )


@app.get("/api/chat/{session_id}")
async def chat_history(
    session_id: str, auth: Optional[dict] = Depends(optional_verify_token)
):
    from backend.chat_store import list_messages

    return {"session_id": session_id, "messages": list_messages(session_id)}


# Lambda handler (for AWS deployment)
try:
    from mangum import Mangum

    handler = Mangum(app, lifespan="off")
except ImportError:
    handler = None


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
