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
import time
import uuid
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
# Uvicorn event loop — used by device_push local in-memory bridge
_app_loop: Optional[asyncio.AbstractEventLoop] = None
# Device-code OAuth style linking (APK shows code → approve on web)
device_link_codes: Dict[str, Dict[str, Any]] = {}  # user_code -> meta


@app.on_event("startup")
async def _capture_app_loop() -> None:
    global _app_loop
    _app_loop = asyncio.get_running_loop()


def _owner_key(auth: Optional[dict]) -> Optional[str]:
    if not auth:
        return None
    return (
        auth.get("email") or auth.get("user_id") or auth.get("sub") or ""
    ).lower() or None


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
    # dry_run: navigate + fill compose, but do NOT tap Send; final screenshot kept
    dry_run: bool = False
    # live_test: real likes (never super-like/paid) + message-bank sends, capped
    live_test: bool = False
    live_test_max_n: int = 3


class TaskStep(BaseModel):
    n: int
    action: str
    reason: Optional[str] = None
    ok: Optional[bool] = True
    package: Optional[str] = None
    screen: Optional[str] = None
    tree_chars: Optional[int] = None
    screenshot_key: Optional[str] = None
    screenshot_url: Optional[str] = None
    verify: Optional[str] = None
    ts: Optional[int] = None
    dry_run: Optional[bool] = None
    planner: Optional[str] = None
    fastpath_step: Optional[str] = None


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
    # llm | heuristic | None — heuristic is open-app-only + labelled in UI
    planner: Optional[str] = None
    llm_provider: Optional[str] = None
    mode: Optional[str] = None
    steps: Optional[List[TaskStep]] = None


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
    # CI/E2E uses dedicated `ci-e2e` so smoke devices never land on Mac/admin.
    user = (request.username or "").strip().lower()
    password = request.password or ""
    admin_pw = os.environ.get("ADMIN_PASSWORD", "admin")
    ci_pw = os.environ.get("CI_E2E_PASSWORD", admin_pw)
    allowed = {
        "admin": admin_pw,
        "ci-e2e": ci_pw,
        "ci_e2e": ci_pw,
    }
    if user in allowed and password == allowed[user]:
        owner = "ci-e2e" if user.startswith("ci") else user
        token = create_access_token({"sub": owner, "email": f"{owner}@local"})
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


class PairClaimRequest(BaseModel):
    token: str
    device_name: str = "Android"
    platform: str = "android"
    device_id: Optional[str] = None


def _load_device_link(key: str) -> Optional[Dict[str, Any]]:
    meta = device_link_codes.get(key)
    if meta:
        return meta
    try:
        from storage import get_device_link_code
    except ImportError:
        from backend.storage import get_device_link_code  # type: ignore

    meta = get_device_link_code(key)
    if meta:
        device_link_codes[key] = meta
        # Keep both indexes warm in this instance
        uc = meta.get("user_code")
        dc = meta.get("device_code")
        if uc:
            device_link_codes[str(uc).upper()] = meta
        if dc:
            device_link_codes[f"dc:{dc}"] = meta
    return meta


def _persist_device_link(meta: Dict[str, Any]) -> None:
    user_code = str(meta.get("user_code") or "").upper()
    device_code = meta.get("device_code")
    if user_code:
        device_link_codes[user_code] = meta
    if device_code:
        device_link_codes[f"dc:{device_code}"] = meta
    try:
        from storage import save_device_link_code
    except ImportError:
        from backend.storage import save_device_link_code  # type: ignore

    if user_code:
        save_device_link_code(user_code, meta)
    if device_code:
        save_device_link_code(f"dc:{device_code}", meta)


@app.post("/api/auth/device/code")
async def start_device_code(body: DeviceCodeStart):
    """
    APK starts a device-code link. Shows user_code; user approves on the web UI
    while signed in with the same Cognito (or local) account.
    Persisted to SETTINGS so Lambda cold starts / multi-instance share the code.
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
    _persist_device_link(meta)
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
    meta = _load_device_link(code)
    if not meta or datetime.now().timestamp() > float(meta.get("expires_at") or 0):
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
    _persist_device_link(meta)
    sess_meta = {
        "device_id": device_id,
        "name": meta["device_name"],
        "platform": meta["platform"],
        "owner": owner,
        "created_at": datetime.now().isoformat(),
    }
    device_sessions[session_token] = sess_meta
    try:
        from storage import save_device_session, upsert_owned_device
    except ImportError:
        from backend.storage import save_device_session, upsert_owned_device  # type: ignore

    save_device_session(session_token, sess_meta)
    # Pre-register device row so it appears in UI immediately (memory + Dynamo)
    row = {
        "device_id": device_id,
        "name": meta["device_name"],
        "platform": meta["platform"],
        "connected": False,
        "connection_type": "pending",
        "owner": owner,
        "last_seen": datetime.now().isoformat(),
    }
    connected_devices[device_id] = {**row, "last_seen": datetime.now()}
    try:
        upsert_owned_device(owner or "", row)
    except Exception:
        logger.exception("persist owned device failed")
    return {"ok": True, "device_id": device_id, "owner": owner}


@app.post("/api/auth/device/token")
async def poll_device_code(body: DeviceCodePoll):
    """APK polls until the user approves the code on the web UI."""
    meta = _load_device_link(f"dc:{body.device_code}")
    if not meta or datetime.now().timestamp() > float(meta.get("expires_at") or 0):
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
    """List devices owned by the signed-in account (memory + Dynamo registry)."""
    try:
        from device_registry import merge_device_lists
    except ImportError:
        from backend.device_registry import merge_device_lists  # type: ignore

    owner = _owner_key(auth)
    merged = merge_device_lists(connected_devices, owner)
    devices = []
    for device_data in merged:
        if not _device_visible_to(device_data, auth):
            continue
        last_seen = device_data.get("last_seen") or datetime.now()
        if isinstance(last_seen, str):
            try:
                last_seen = datetime.fromisoformat(last_seen.replace("Z", ""))
            except ValueError:
                last_seen = datetime.now()
        devices.append(
            DeviceInfo(
                device_id=str(device_data.get("device_id")),
                name=str(device_data.get("name") or device_data.get("device_id")),
                platform=str(device_data.get("platform") or "android"),
                connected=bool(device_data.get("connected", False)),
                connection_type=str(device_data.get("connection_type") or "unknown"),
                last_seen=last_seen,
                route=device_data.get("route"),
                latency_ms=device_data.get("latency_ms"),
                permissions=device_data.get("permissions"),
            )
        )
    return devices


def _health_payload() -> dict:
    return {
        "status": "ok",
        "service": "mobilerun",
        "step_driven": os.environ.get("STEP_DRIVEN", "false"),
        "use_aws_storage": os.environ.get("USE_AWS_STORAGE", "false"),
        "websocket_api": os.environ.get("WEBSOCKET_API_ENDPOINT", ""),
        "mdns_service": "_mobilerun._tcp",
        "usb_required": False,
    }


@app.get("/health")
@app.get("/api/health")
async def health():
    """Public health check (no auth). `/health` alias for probes / APK."""
    return _health_payload()


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


def _pairing_endpoints() -> dict:
    from mobilerun.connectivity.endpoints import http_to_ws

    cloud_http = (
        os.environ.get("BACKEND_URL")
        or os.environ.get("API_URL")
        or "https://68tgk4z5n6.execute-api.eu-west-2.amazonaws.com"
    )
    cloud_ws = (
        os.environ.get("WEBSOCKET_API_ENDPOINT")
        or "wss://sv7144gijj.execute-api.eu-west-2.amazonaws.com/prod"
    )
    lan_http, lan_ws = _lan_endpoints()
    use_aws = os.environ.get("USE_AWS_STORAGE", "false").lower() == "true"
    if use_aws and cloud_http:
        return {
            "backend_url": cloud_http,
            "websocket_url": cloud_ws or http_to_ws(cloud_http),
            "lan_http": None,
            "lan_ws": None,
            "cloud_http": cloud_http,
            "cloud_ws": cloud_ws or http_to_ws(cloud_http),
        }
    cloud_http_out = cloud_http or os.environ.get("CLOUD_BACKEND_URL") or None
    cloud_ws_out = (
        cloud_ws
        or os.environ.get("CLOUD_WEBSOCKET_URL")
        or (http_to_ws(cloud_http_out) if cloud_http_out else None)
    )
    return {
        "backend_url": lan_http,
        "websocket_url": lan_ws,
        "lan_http": lan_http,
        "lan_ws": lan_ws,
        "cloud_http": cloud_http_out,
        "cloud_ws": cloud_ws_out,
    }


def _qr_png_b64(data: str) -> str:
    """High-contrast QR tuned for phone cameras scanning a laptop screen.

    Short payloads (e.g. https://…/p/ABC12345) stay at low QR version.
    Error correction M + large quiet zone for robust decode.
    """
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=12,
        border=6,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return base64.b64encode(buf.getvalue()).decode()


async def _create_pairing_token(request: PairingRequest, owner: Optional[str]):
    from mobilerun.connectivity.endpoints import build_pairing_url

    try:
        from backend.pairing_security import check_rate_limit
    except ImportError:
        from pairing_security import check_rate_limit  # type: ignore
    try:
        from backend.pairing_codes import generate_pairing_code
    except ImportError:
        from pairing_codes import generate_pairing_code  # type: ignore

    if not check_rate_limit(
        f"pair-create:{owner or 'anon'}", limit=10, window_seconds=60
    ):
        raise HTTPException(
            status_code=429, detail="Too many pairing codes — try again shortly"
        )

    try:
        from storage import get_pairing_token, save_pairing_token
    except ImportError:
        from backend.storage import get_pairing_token, save_pairing_token  # type: ignore

    # Short typeable code (also the claim token) — APK has baked prod URLs.
    token = None
    for _ in range(12):
        candidate = generate_pairing_code(8)
        if candidate in pairing_tokens:
            continue
        if get_pairing_token(candidate):
            continue
        token = candidate
        break
    if not token:
        raise HTTPException(status_code=503, detail="Could not allocate pairing code")

    ends = _pairing_endpoints()
    expires_at = datetime.now().timestamp() + 600
    pairing_data = {
        "device_name": request.device_name,
        "platform": request.platform,
        "created_at": datetime.now().isoformat(),
        "expires_at": expires_at,
        "owner": owner,
        "used": False,
        "code": token,
        **ends,
    }
    pairing_tokens[token] = {**pairing_data, "token": token}

    # Persist hashed — never store plaintext token. Fail closed if Dynamo write
    # fails so claim on another Lambda cold start cannot miss the token.
    try:
        save_pairing_token(
            token,
            {
                **pairing_data,
                "owner": owner,
            },
        )
    except Exception:
        logger.exception("save_pairing_token failed for owner=%s", owner)
        raise HTTPException(
            status_code=503, detail="Could not persist pairing code — retry"
        )

    # Compact deep link: short code only (c=) — QR encodes even shorter HTTPS /p/CODE
    pairing_url = build_pairing_url(
        token=token,
        backend=ends["backend_url"],
        ws=ends["websocket_url"],
        lan_http=ends["lan_http"],
        lan_ws=ends["lan_ws"],
        cloud_http=ends["cloud_http"],
        cloud_ws=ends["cloud_ws"],
        compact=True,
    )
    pairing_url_full = build_pairing_url(
        token=token,
        backend=ends["backend_url"],
        ws=ends["websocket_url"],
        lan_http=ends["lan_http"],
        lan_ws=ends["lan_ws"],
        cloud_http=ends["cloud_http"],
        cloud_ws=ends["cloud_ws"],
        compact=False,
    )
    frontend = (
        os.environ.get("FRONTEND_URL")
        or os.environ.get("NETLIFY_URL")
        or "https://macsmobilerun.netlify.app"
    ).rstrip("/")
    # Tiny QR payload: /p/CODE (low QR version). Pair landing opens mobilerun://.
    short_https = f"{frontend}/p/{token}"
    https_link = short_https

    return {
        "token": token,
        "code": token,
        "qr_code": _qr_png_b64(short_https),
        "qr_payload": short_https,
        "pairing_url": pairing_url,
        "pairing_url_full": pairing_url_full,
        "https_link": https_link,
        "short_link": short_https,
        "backend_url": ends["backend_url"],
        "websocket_url": ends["websocket_url"],
        "lan_http": ends["lan_http"],
        "lan_ws": ends["lan_ws"],
        "cloud_http": ends["cloud_http"],
        "cloud_ws": ends["cloud_ws"],
        "mdns_service": "_mobilerun._tcp",
        "device_name": request.device_name,
        "expires_in": 600,
        "owner": owner,
    }


@app.post("/api/devices/pair")
@app.post("/api/auth/pair/create")
async def initiate_pairing(
    request: PairingRequest, auth: Optional[dict] = Depends(optional_verify_token)
):
    """
    Signed-in user creates a short-lived (~10 min), single-use pairing QR/link
    tied to their Cognito account. Token is hashed at rest.
    Local/dev: ALLOW_UNAUTHENTICATED permits owner=local.
    """
    if auth is None:
        if os.environ.get("ALLOW_UNAUTHENTICATED", "false").lower() != "true":
            raise HTTPException(
                status_code=401, detail="Sign in to create a pairing QR"
            )
        owner = "local"
    else:
        owner = _owner_key(auth)
    return await _create_pairing_token(request, owner)


@app.post("/api/auth/pair/claim")
async def claim_pairing_token(body: PairClaimRequest):
    """APK exchanges single-use QR token for a long-lived device session_token."""
    try:
        from backend.pairing_security import check_rate_limit
    except ImportError:
        from pairing_security import check_rate_limit  # type: ignore
    try:
        from storage import (
            delete_pairing_token,
            get_pairing_token,
            save_device_session,
            upsert_owned_device,
        )
    except ImportError:
        from backend.storage import (  # type: ignore
            delete_pairing_token,
            get_pairing_token,
            save_device_session,
            upsert_owned_device,
        )

    try:
        from backend.pairing_codes import normalize_pairing_code
    except ImportError:
        from pairing_codes import normalize_pairing_code  # type: ignore

    token = normalize_pairing_code(body.token) or (body.token or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="token required")
    if not check_rate_limit(f"pair-claim:{token[:16]}", limit=8, window_seconds=60):
        raise HTTPException(status_code=429, detail="Too many claim attempts")

    meta = pairing_tokens.get(token) or get_pairing_token(token)
    # Case-insensitive fallback for short codes
    if not meta and token != token.upper():
        meta = pairing_tokens.get(token.upper()) or get_pairing_token(token.upper())
        if meta:
            token = token.upper()
    if not meta:
        logger.warning("pair claim miss token_prefix=%s len=%s", token[:8], len(token))
        raise HTTPException(status_code=400, detail="Invalid or expired pairing token")
    if meta.get("used"):
        raise HTTPException(status_code=400, detail="Pairing token already used")
    expires = float(meta.get("expires_at") or 0)
    if datetime.now().timestamp() > expires:
        pairing_tokens.pop(token, None)
        try:
            delete_pairing_token(token)
        except Exception:
            pass
        raise HTTPException(status_code=400, detail="Pairing token expired")

    owner = (meta.get("owner") or "").lower()
    if not owner:
        raise HTTPException(status_code=400, detail="Pairing token has no owner")
    logger.info(
        "pair claim ok owner=%s device_name=%s",
        owner,
        body.device_name or meta.get("device_name"),
    )

    device_id = body.device_id or f"device_{secrets.token_hex(8)}"
    session_token = secrets.token_urlsafe(32)
    name = body.device_name or meta.get("device_name") or "Android"
    platform = body.platform or meta.get("platform") or "android"
    sess_meta = {
        "device_id": device_id,
        "name": name,
        "platform": platform,
        "owner": owner,
        "created_at": datetime.now().isoformat(),
        "revoked": False,
    }
    device_sessions[session_token] = sess_meta
    save_device_session(session_token, sess_meta)
    row = {
        "device_id": device_id,
        "name": name,
        "platform": platform,
        "connected": False,
        "connection_type": "pending",
        "owner": owner,
        "session_token": session_token,
        "last_seen": datetime.now().isoformat(),
    }
    connected_devices[device_id] = {**row, "last_seen": datetime.now()}
    upsert_owned_device(owner, row)

    pairing_tokens.pop(token, None)
    try:
        delete_pairing_token(token)
    except Exception:
        logger.exception("delete pairing token failed")

    access = create_access_token(
        {"sub": owner, "email": owner, "device_id": device_id, "role": "device"}
    )
    return {
        "access_token": access,
        "session_token": session_token,
        "device_id": device_id,
        "owner": owner,
        "token_type": "bearer",
        "cloud_http": meta.get("cloud_http")
        or meta.get("backend_url")
        or "https://68tgk4z5n6.execute-api.eu-west-2.amazonaws.com",
        "cloud_ws": meta.get("cloud_ws")
        or meta.get("websocket_url")
        or "wss://sv7144gijj.execute-api.eu-west-2.amazonaws.com/prod",
    }


@app.delete("/api/devices/{device_id}")
async def revoke_device(
    device_id: str, auth: Optional[dict] = Depends(optional_verify_token)
):
    """Revoke a phone's long-lived credential and remove it from the owner's list."""
    if auth is None:
        raise HTTPException(status_code=401, detail="Sign in to revoke a device")
    owner = _owner_key(auth)
    try:
        from storage import get_user_setting, remove_owned_device, revoke_device_session
    except ImportError:
        from backend.storage import (  # type: ignore
            get_user_setting,
            remove_owned_device,
            revoke_device_session,
        )

    blob = get_user_setting(owner or "", "devices") or {}
    row = (blob.get("devices") or {}).get(device_id) or connected_devices.get(device_id)
    if not row or (row.get("owner") or "").lower() != (owner or "").lower():
        raise HTTPException(status_code=404, detail="Device not found")
    st = row.get("session_token")
    if st:
        device_sessions.pop(st, None)
        revoke_device_session(str(st))
    remove_owned_device(owner or "", device_id)
    connected_devices.pop(device_id, None)
    return {"ok": True, "device_id": device_id, "revoked": True}


@app.get("/api/devices/{device_id}/agent_debug")
async def device_agent_debug(
    device_id: str, auth: Optional[dict] = Depends(optional_verify_token)
):
    """Reachability + live WS connection rows (diagnose idle-0 / tick failures)."""
    try:
        from storage import device_is_ws_connected, get_device_connections
    except ImportError:
        from backend.storage import (  # type: ignore
            device_is_ws_connected,
            get_device_connections,
        )
    try:
        from device_push import device_is_reachable
    except ImportError:
        from backend.device_push import device_is_reachable  # type: ignore

    conns = []
    try:
        raw = get_device_connections(device_id) or []
        now = int(time.time())
        for c in raw:
            ca = int(c.get("connected_at") or 0)
            conns.append(
                {
                    "connection_id": str(c.get("connection_id") or "")[:12] + "…",
                    "role": c.get("role"),
                    "authed": bool(c.get("authed")),
                    "platform": c.get("platform"),
                    "age_s": (now - ca) if ca else None,
                    "last_type": c.get("last_type"),
                    "owner": (c.get("owner") or "")[:32],
                }
            )
    except Exception as e:
        conns = [{"error": str(e)}]
    return {
        "device_id": device_id,
        "reachable": bool(device_is_reachable(device_id)),
        "ws_connected": bool(device_is_ws_connected(device_id)),
        "connections": conns,
        "in_memory_ws": device_id in device_websockets,
        "step_worker_arn_set": bool(os.environ.get("STEP_WORKER_ARN")),
        "use_aws_storage": os.environ.get("USE_AWS_STORAGE"),
    }


class DeviceRpcBody(BaseModel):
    command: str
    params: Optional[Dict[str, Any]] = None
    timeout_s: float = 20.0


@app.post("/api/devices/{device_id}/rpc")
async def device_rpc_http(
    device_id: str,
    body: DeviceRpcBody,
    auth: Optional[dict] = Depends(optional_verify_token),
):
    """One-shot phone RPC (get_device_info / ensure_ime / get_ui_tree) via WS.

    Used to confirm APK build + IME without waiting on the full agent loop.
    """
    if auth is None and os.environ.get("ALLOW_UNAUTHENTICATED", "").lower() != "true":
        raise HTTPException(status_code=401, detail="Sign in required")
    cmd = (body.command or "").strip()
    # Allowlist — never expose arbitrary shell/file commands here
    allowed = {
        "get_device_info",
        "ensure_ime",
        "restore_ime",
        "get_ui_tree",
        "screenshot",
        "ping",
        "get_foreground_app",
        "dismiss_dialogs",
    }
    if cmd not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"command not allowed; choose from {sorted(allowed)}",
        )

    try:
        from device_rpc import call_device
    except ImportError:
        from backend.device_rpc import call_device  # type: ignore

    t0 = time.time()
    try:
        result = await asyncio.to_thread(
            call_device,
            device_id,
            cmd,
            body.params or {},
            float(body.timeout_s or 20.0),
            wait_reconnect_s=min(30.0, float(body.timeout_s or 20.0)),
        )
        return {
            "ok": True,
            "device_id": device_id,
            "command": cmd,
            "result": result,
            "elapsed_s": round(time.time() - t0, 3),
        }
    except Exception as e:
        return {
            "ok": False,
            "device_id": device_id,
            "command": cmd,
            "error": str(e),
            "elapsed_s": round(time.time() - t0, 3),
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
            if sess.get("revoked"):
                await websocket.send_json({"error": "Session revoked"})
                await websocket.close()
                return
            device_id = sess["device_id"]
            owner = sess.get("owner")
            pairing_data = {
                "device_name": sess.get("name") or device_id,
                "platform": sess.get("platform", "android"),
                "owner": owner,
            }
        elif session_token:
            try:
                from storage import get_device_session
            except ImportError:
                from backend.storage import get_device_session  # type: ignore

            sess = get_device_session(str(session_token)) or {}
            if not sess.get("device_id") or sess.get("revoked"):
                await websocket.send_json({"error": "Invalid or expired session"})
                await websocket.close()
                return
            device_id = sess["device_id"]
            owner = sess.get("owner")
            device_sessions[session_token] = sess
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
                "device_name": data.get("device_name") or data.get("name") or "Android",
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
        elif token:
            try:
                from storage import delete_pairing_token, get_pairing_token
            except ImportError:
                from backend.storage import (  # type: ignore
                    delete_pairing_token,
                    get_pairing_token,
                )

            pairing_data = pairing_tokens.get(token) or get_pairing_token(token)
            if not pairing_data:
                await websocket.send_json(
                    {"error": "Invalid or expired token / session"}
                )
                await websocket.close()
                return
            if datetime.now().timestamp() > float(pairing_data.get("expires_at") or 0):
                await websocket.send_json({"error": "Token expired"})
                await websocket.close()
                pairing_tokens.pop(token, None)
                try:
                    delete_pairing_token(token)
                except Exception:
                    pass
                return
            device_id = data.get("device_id") or f"device_{secrets.token_hex(8)}"
            owner = pairing_data.get("owner")
            pairing_tokens.pop(token, None)
            try:
                delete_pairing_token(token)
            except Exception:
                pass
            # Issue reconnect session
            session_token = secrets.token_urlsafe(32)
            device_sessions[session_token] = {
                "device_id": device_id,
                "name": pairing_data.get("device_name") or "Android",
                "platform": pairing_data.get("platform") or "android",
                "owner": owner,
                "created_at": datetime.now().isoformat(),
            }
            pairing_data = {
                "device_name": pairing_data.get("device_name") or "Android",
                "platform": pairing_data.get("platform") or "android",
                "owner": owner,
            }
        else:
            await websocket.send_json({"error": "Invalid or expired token / session"})
            await websocket.close()
            return

        conn_type = route if route in ("lan", "cloud", "discovered") else "wifi"
        owner_final = owner or pairing_data.get("owner")
        connected_devices[device_id] = {
            "device_id": device_id,
            "name": pairing_data["device_name"],
            "platform": pairing_data["platform"],
            "connected": True,
            "connection_type": conn_type,
            "route": conn_type,
            "latency_ms": latency_ms,
            "owner": owner_final,
            "last_seen": datetime.now(),
        }
        if owner_final:
            try:
                from storage import save_device_session, upsert_owned_device
            except ImportError:
                from backend.storage import (  # type: ignore
                    save_device_session,
                    upsert_owned_device,
                )

            if session_token:
                save_device_session(
                    session_token,
                    {
                        "device_id": device_id,
                        "name": pairing_data["device_name"],
                        "platform": pairing_data["platform"],
                        "owner": owner_final,
                    },
                )
            upsert_owned_device(
                owner_final,
                {
                    "device_id": device_id,
                    "name": pairing_data["device_name"],
                    "platform": pairing_data["platform"],
                    "connected": True,
                    "connection_type": conn_type,
                    "route": conn_type,
                    "latency_ms": latency_ms,
                    "last_seen": datetime.now().isoformat(),
                },
            )

        device_websockets[device_id] = websocket
        global _app_loop
        try:
            _app_loop = asyncio.get_running_loop()
        except RuntimeError:
            pass

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
    """Prefer in-memory WS (local); fall back to API GW Management API (AWS)."""
    ws = device_websockets.get(device_id)
    if ws:
        try:
            await ws.send_json(payload)
            return True
        except Exception as e:
            logger.warning("in-memory send to %s failed: %s", device_id, e)
    try:
        from backend.device_push import push_to_device
    except ImportError:
        try:
            from device_push import push_to_device  # type: ignore
        except ImportError:
            return False
    return push_to_device(device_id, payload)


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
        # Refresh durable registry so HTTP list_devices stays accurate
        dev = connected_devices.get(device_id) or {}
        owner = (dev.get("owner") or "").lower()
        if owner:
            try:
                from storage import upsert_owned_device
            except ImportError:
                from backend.storage import upsert_owned_device  # type: ignore

            upsert_owned_device(
                owner,
                {
                    "device_id": device_id,
                    "name": dev.get("name") or device_id,
                    "platform": dev.get("platform") or "android",
                    "connected": True,
                    "connection_type": dev.get("connection_type") or "websocket",
                    "route": dev.get("route"),
                    "latency_ms": dev.get("latency_ms"),
                    "last_seen": datetime.now().isoformat(),
                },
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
        owner = (dev.get("owner") or "").lower()
        if owner:
            try:
                from storage import upsert_owned_device
            except ImportError:
                from backend.storage import upsert_owned_device  # type: ignore

            upsert_owned_device(
                owner,
                {
                    "device_id": device_id,
                    "name": dev.get("name") or device_id,
                    "platform": dev.get("platform") or "android",
                    "connected": True,
                    "permissions": perms,
                    "last_seen": datetime.now().isoformat(),
                },
            )
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

    elif msg_type == "response":
        rid = message.get("request_id")
        if rid:
            try:
                from device_rpc import store_rpc_response
            except ImportError:
                from backend.device_rpc import store_rpc_response  # type: ignore

            store_rpc_response(
                str(rid),
                {"error": message.get("error"), "result": message.get("result")},
            )
        await broadcast_to_ui(
            device_id, {"type": "response", "device_id": device_id, **message}
        )

    elif msg_type == "screenshot":
        # Optional one-shot screenshot — fan out if UI cares
        await broadcast_to_ui(
            device_id, {"type": msg_type, "device_id": device_id, **message}
        )


@app.post("/api/tasks", response_model=TaskStatus)
async def submit_task(
    request: TaskRequest, auth: Optional[dict] = Depends(optional_verify_token)
):
    """Submit a new automation task to a device."""
    mem = connected_devices.get(request.device_id) or {}
    try:
        from backend.device_push import device_is_reachable
    except ImportError:
        try:
            from device_push import device_is_reachable  # type: ignore
        except ImportError:
            device_is_reachable = lambda _d: False  # type: ignore

    reachable = bool(mem.get("connected")) or device_is_reachable(request.device_id)
    if not mem and not reachable:
        # Still allow if owned device exists in Dynamo (offline → clear error)
        owner = _owner_key(auth)
        owned = False
        if owner:
            try:
                from storage import list_owned_devices
            except ImportError:
                from backend.storage import list_owned_devices  # type: ignore

            owned = any(
                str(d.get("device_id")) == request.device_id
                for d in list_owned_devices(owner)
            )
        if not owned:
            raise HTTPException(status_code=404, detail="Device not found")
        raise HTTPException(
            status_code=400,
            detail="Device offline — open MobileRun on the phone and wait until Devices shows Connected",
        )
    if not reachable:
        raise HTTPException(
            status_code=400,
            detail="Device offline — no live WebSocket. Re-open the app on the phone.",
        )

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

    # Cloud agent loop (step worker) drives the phone via WS commands.
    # Do NOT rely on the APK keyword stub for multi-step goals.
    try:
        try:
            from storage import put_job
        except ImportError:
            from backend.storage import put_job  # type: ignore

        put_job(
            {
                "job_id": task_id,
                "kind": "agent",
                "status": "running",
                "device_id": request.device_id,
                "instruction": request.instruction,
                "max_steps": request.max_steps or 15,
                "speed_preset": speed,
                "mode": mode,
                "dry_run": bool(request.dry_run) and not bool(request.live_test),
                "live_test": bool(request.live_test),
                "live_test_max_n": int(request.live_test_max_n or 3),
                "created_at": int(datetime.now().timestamp()),
                "next_run_at": int(datetime.now().timestamp()),
                "state": {
                    "steps": 0,
                    "history": [],
                    "dry_run": bool(request.dry_run) and not bool(request.live_test),
                    "live_test": bool(request.live_test),
                    "live_test_max_n": int(request.live_test_max_n or 3),
                    "live_likes_done": 0,
                    "live_messages_done": 0,
                },
                "ttl": int(datetime.now().timestamp()) + 86400,
                "result": "Queued for cloud agent",
            }
        )
    except Exception as e:
        logger.warning("put_job for task failed (local ok): %s", e)

    # Notify phone that a cloud-driven task started (optional; agent uses commands)
    await _send_to_device(
        request.device_id,
        {
            "type": "agent_control",
            "action": "start",
            "task_id": task_id,
            "instruction": request.instruction,
            "max_steps": request.max_steps,
            "mode": mode,
            "speed_preset": speed,
        },
    )

    kicked = False
    try:
        step_arn = os.environ.get("STEP_WORKER_ARN")
        if step_arn and os.environ.get("USE_AWS_STORAGE") == "true":
            import boto3

            boto3.client("lambda").invoke(
                FunctionName=step_arn,
                InvocationType="Event",
                Payload=json.dumps({"job_id": task_id}).encode(),
            )
            kicked = True
            task["status"] = "running"
            task["result"] = "Cloud agent started (step worker)"
        elif os.environ.get("ALLOW_UNAUTHENTICATED", "").lower() == "true":
            # Local/dev: queue the job; /api/jobs/{id}/tick advances steps off the
            # event loop (asyncio.to_thread) so in-memory WS RPC can complete.
            # Do NOT run steps inline here — that deadlocks get_ui_tree.
            kicked = True
            task["status"] = "running"
            task["result"] = "Queued for local tick loop"
    except Exception as e:
        logger.error("Failed to kick cloud agent: %s", e)
        task["status"] = "failed"
        task["error"] = f"Failed to start cloud agent: {e}"

    if not kicked and task["status"] != "failed":
        task["status"] = "failed"
        task["error"] = (
            "Step worker not configured — cannot run cloud agent on this backend"
        )

    return TaskStatus(**task)


@app.get("/api/tasks/{task_id}", response_model=TaskStatus)
async def get_task_status(
    task_id: str, auth: Optional[dict] = Depends(optional_verify_token)
):
    """Get status of a specific task (durable Dynamo job preferred over memory)."""
    try:
        from storage import get_job
    except ImportError:
        from backend.storage import get_job  # type: ignore

    job = None
    try:
        job = get_job(task_id)
    except Exception:
        job = None

    mem = active_runs.get(task_id)
    if not mem:
        for run in run_history:
            if run["task_id"] == task_id:
                mem = run
                break

    # Prefer durable job when present so WS task_update progress is visible
    # across HTTP Lambda instances (in-memory active_runs stays stale).
    if job:
        started = job.get("created_at") or job.get("started_at")
        if isinstance(started, (int, float)):
            started_at = datetime.fromtimestamp(float(started))
        elif mem and mem.get("started_at"):
            started_at = mem["started_at"]
        else:
            started_at = datetime.now()
        completed = job.get("completed_at")
        completed_at = (
            datetime.fromtimestamp(float(completed))
            if isinstance(completed, (int, float))
            else (mem or {}).get("completed_at")
        )
        status = str(job.get("status") or (mem or {}).get("status") or "pending")
        result = job.get("result") or (job.get("state") or {}).get("last_action")
        if mem:
            mem["status"] = status
            if result is not None:
                mem["result"] = result
            if completed_at is not None:
                mem["completed_at"] = completed_at
        st = job.get("state") or {}
        # Timeout stale running jobs on read
        if status == "running":
            created = job.get("created_at")
            try:
                from cloud_agent import TASK_TIMEOUT_S
            except ImportError:
                from backend.cloud_agent import TASK_TIMEOUT_S  # type: ignore
            timed_out = False
            if isinstance(created, (int, float)) and (
                time.time() - float(created) > TASK_TIMEOUT_S
            ):
                status = "failed"
                job["status"] = "failed"
                job["error"] = (
                    job.get("error") or f"Task timed out after {TASK_TIMEOUT_S}s"
                )
                timed_out = True
            else:
                # Idle + no-UI-progress walls on read path (r23: hung jobs
                # stayed running until Mac cancelled — StepWorker missed them).
                try:
                    from cloud_agent import (
                        NO_PROGRESS_TIMEOUT_S,
                        TASK_IDLE_TIMEOUT_S,
                    )
                except ImportError:
                    from backend.cloud_agent import (  # type: ignore
                        NO_PROGRESS_TIMEOUT_S,
                        TASK_IDLE_TIMEOUT_S,
                    )

                st_job = job.get("state") or {}
                last_ui = st_job.get("last_ui_progress_at") or created
                steps_n = int(st_job.get("steps") or 0)
                if (
                    isinstance(last_ui, (int, float))
                    and steps_n >= 1
                    and (time.time() - float(last_ui) > NO_PROGRESS_TIMEOUT_S)
                ):
                    status = "failed"
                    job["status"] = "failed"
                    job["error"] = job.get("error") or (
                        f"No UI progress for {NO_PROGRESS_TIMEOUT_S}s "
                        f"(read-path hard wall)"
                    )
                    timed_out = True
                else:
                    last_p = st_job.get("last_progress_at") or created
                    if isinstance(last_p, (int, float)) and (
                        time.time() - float(last_p) > TASK_IDLE_TIMEOUT_S
                    ):
                        status = "failed"
                        job["status"] = "failed"
                        job["error"] = job.get("error") or (
                            f"Task idle for {TASK_IDLE_TIMEOUT_S}s "
                            f"with no step progress"
                        )
                        timed_out = True
            if timed_out:
                try:
                    from storage import put_job as _put

                    _put(job)
                except Exception:
                    try:
                        from backend.storage import put_job as _put  # type: ignore

                        _put(job)
                    except Exception:
                        pass
        steps = _task_steps_from_state(st)
        return TaskStatus(
            task_id=task_id,
            device_id=str(job.get("device_id") or (mem or {}).get("device_id") or ""),
            instruction=str(
                job.get("instruction") or (mem or {}).get("instruction") or ""
            ),
            status=status,
            current_step=int(st.get("steps") or 0),
            max_steps=int(job.get("max_steps") or (mem or {}).get("max_steps") or 15),
            result=result if result is not None else (mem or {}).get("result"),
            error=job.get("error") or (mem or {}).get("error"),
            started_at=started_at,
            completed_at=completed_at,
            planner=st.get("planner") or (mem or {}).get("planner"),
            llm_provider=st.get("llm_provider") or (mem or {}).get("llm_provider"),
            mode=str(job.get("mode") or (mem or {}).get("mode") or "normal"),
            steps=steps,
        )

    if mem:
        return TaskStatus(**mem)

    raise HTTPException(status_code=404, detail="Task not found")


def _task_steps_from_state(st: Dict[str, Any]) -> List[TaskStep]:
    raw = list(st.get("steps_detail") or [])
    out: List[TaskStep] = []
    bucket = os.environ.get("SCREENSHOT_BUCKET") or ""
    for s in raw:
        if not isinstance(s, dict):
            continue
        key = s.get("screenshot_key")
        url = None
        if key and bucket:
            # Presign lightly so History can show thumbs (short TTL)
            try:
                import boto3

                url = boto3.client("s3").generate_presigned_url(
                    "get_object",
                    Params={"Bucket": bucket, "Key": key},
                    ExpiresIn=3600,
                )
            except Exception:
                url = None
        out.append(
            TaskStep(
                n=int(s.get("n") or 0),
                action=str(s.get("action") or ""),
                reason=s.get("reason"),
                ok=s.get("ok", True),
                package=s.get("package"),
                screen=s.get("screen") or s.get("package"),
                tree_chars=s.get("tree_chars"),
                screenshot_key=key,
                screenshot_url=url,
                verify=s.get("verify"),
                ts=s.get("ts"),
                dry_run=s.get("dry_run"),
                planner=s.get("planner"),
                fastpath_step=s.get("fastpath_step"),
            )
        )
    # Fallback: derive from flat history strings
    if not out:
        for i, h in enumerate(st.get("history") or []):
            out.append(TaskStep(n=i + 1, action=str(h), reason=None, ok=True))
    return out


@app.get("/api/tasks", response_model=List[TaskStatus])
async def list_tasks(
    limit: int = 50, auth: Optional[dict] = Depends(optional_verify_token)
):
    """List recent tasks (Dynamo jobs preferred over in-memory)."""
    jobs: List[Dict[str, Any]] = []
    try:
        from storage import list_recent_jobs
    except ImportError:
        from backend.storage import list_recent_jobs  # type: ignore
    try:
        jobs = list_recent_jobs(limit=limit)
    except Exception as e:
        logger.warning("list_recent_jobs failed: %s", e)

    out: List[TaskStatus] = []
    for job in jobs:
        # Skip dating loop jobs from Normal history unless mode matches
        kind = str(job.get("kind") or "agent")
        if kind not in ("agent", "task"):
            # Include dating/social loop jobs in History with mode label
            if kind not in ("dating", "social"):
                continue
        st = job.get("state") or {}
        started = job.get("created_at") or job.get("started_at")
        if isinstance(started, (int, float)):
            started_at = datetime.fromtimestamp(float(started))
        else:
            started_at = datetime.now()
        completed = job.get("completed_at")
        completed_at = (
            datetime.fromtimestamp(float(completed))
            if isinstance(completed, (int, float))
            else None
        )
        out.append(
            TaskStatus(
                task_id=str(job.get("job_id") or ""),
                device_id=str(job.get("device_id") or ""),
                instruction=str(job.get("instruction") or kind),
                status=str(job.get("status") or "unknown"),
                current_step=int(st.get("steps") or 0),
                max_steps=int(job.get("max_steps") or 15),
                result=job.get("result") or st.get("last_action"),
                error=job.get("error"),
                started_at=started_at,
                completed_at=completed_at,
                planner=st.get("planner"),
                llm_provider=st.get("llm_provider"),
                mode=str(job.get("mode") or kind),
                steps=_task_steps_from_state(st),
            )
        )
    if out:
        return out[:limit]

    # Local fallback
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
    try:
        from cloud_agent import _key_presence
    except ImportError:
        from backend.cloud_agent import _key_presence  # type: ignore

    return {
        "provider": provider,
        "model": os.environ.get("LLM_MODEL", default_model),
        "temperature": float(os.environ.get("LLM_TEMPERATURE", "0.7")),
        "max_tokens": int(os.environ.get("LLM_MAX_TOKENS", "2048")),
        "supported_providers": list(SUPPORTED_LLM_PROVIDERS),
        "default_models": dict(DEFAULT_LLM_MODELS),
        "xai_api_base": "https://api.x.ai/v1",
        "keys_present": _key_presence(),
    }


@app.post("/api/config/llm/probe")
async def probe_llm_config(auth: Optional[dict] = Depends(optional_verify_token)):
    """Real Gemini/OpenAI HTTP probes from this Lambda (no secret values)."""
    try:
        from cloud_agent import probe_llm_providers
    except ImportError:
        from backend.cloud_agent import probe_llm_providers  # type: ignore

    return probe_llm_providers()


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


def _latest_apk_release() -> dict:
    """Resolve newest GitHub release tagged apk-N (skips apk-preview-*)."""
    import re
    import urllib.request

    repo = os.environ.get("GITHUB_REPO") or "MacAndersonUche/mobilerun"
    api = f"https://api.github.com/repos/{repo}/releases?per_page=30"
    req = urllib.request.Request(
        api,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "mobilerun-backend",
        },
    )
    best: Optional[dict] = None
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            releases = json.loads(resp.read().decode() or "[]")
    except Exception as e:
        logger.warning("GitHub releases fetch failed: %s", e)
        releases = []
    tag_re = re.compile(r"^apk-(\d+)$")
    for rel in releases or []:
        if not isinstance(rel, dict) or rel.get("draft"):
            continue
        tag = str(rel.get("tag_name") or "")
        m = tag_re.match(tag)
        if not m:
            continue
        code = int(m.group(1))
        apk_url = ""
        for asset in rel.get("assets") or []:
            name = str((asset or {}).get("name") or "")
            url = str((asset or {}).get("browser_download_url") or "")
            if name.lower() == "mobilerun.apk":
                apk_url = url
                break
            if name.endswith(".apk") and not apk_url:
                apk_url = url
        if not apk_url:
            apk_url = f"https://github.com/{repo}/releases/download/{tag}/mobilerun.apk"
        row = {
            "version_code": code,
            "version_name": f"1.0.{code}",
            "version": f"1.0.{code}",
            "tag": tag,
            "apk_url": apk_url,
            "release_notes": str(rel.get("body") or "")[:2000],
        }
        if best is None or code > int(best["version_code"]):
            best = row
    if best is None:
        latest_url = f"https://github.com/{repo}/releases/latest/download/mobilerun.apk"
        best = {
            "version_code": 0,
            "version_name": "latest",
            "version": "latest",
            "tag": "latest",
            "apk_url": latest_url,
            "release_notes": "Latest build from main branch",
        }
    return best


@app.get("/api/releases/latest")
async def get_latest_release():
    """Get latest apk-N release info with QR code (used by in-app self-update)."""
    info = await asyncio.to_thread(_latest_apk_release)
    apk_url = str(info.get("apk_url") or "")

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(apk_url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    qr_base64 = base64.b64encode(buf.getvalue()).decode()

    return {
        **info,
        "qr_code": qr_base64,
    }


class PushUpdateBody(BaseModel):
    version_code: Optional[int] = None
    version_name: Optional[str] = None
    tag: Optional[str] = None
    apk_url: Optional[str] = None


@app.post("/api/devices/{device_id}/push_update")
async def push_update_available(
    device_id: str,
    body: Optional[PushUpdateBody] = None,
    auth: Optional[dict] = Depends(optional_verify_token),
):
    """Push an `update_available` WS message so the phone can self-update."""
    if auth is None and os.environ.get("ALLOW_UNAUTHENTICATED", "").lower() != "true":
        raise HTTPException(status_code=401, detail="Sign in required")
    info = await asyncio.to_thread(_latest_apk_release)
    code = (body.version_code if body and body.version_code else None) or int(
        info.get("version_code") or 0
    )
    tag = (body.tag if body and body.tag else None) or str(
        info.get("tag") or f"apk-{code}"
    )
    name = (body.version_name if body and body.version_name else None) or str(
        info.get("version_name") or f"1.0.{code}"
    )
    apk_url = (body.apk_url if body and body.apk_url else None) or str(
        info.get("apk_url") or ""
    )
    payload = {
        "type": "update_available",
        "version_code": code,
        "version_name": name,
        "tag": tag,
        "apk_url": apk_url,
    }
    ok = await _send_to_device(device_id, payload)
    return {"ok": bool(ok), "device_id": device_id, "payload": payload}


# === Dating Mode API ===

dating_mode_state = {
    "running": False,
    "paused": False,
    "current_app": None,
    "review_queue": [],
    "review_before_send": True,
    "speed_preset": "balanced",
    "opener_mode": "templates",  # templates | ai
    "opener_library": None,
    "date_flow": None,
}

social_mode_state = {
    "running": False,
    "paused": False,
    "current_app": None,
    "speed_preset": "balanced",
    "unread": {"total_unread": 0, "by_app": {}},
    "job_id": None,
}

# Global agent mode selection (UI / CLI / chat)
agent_mode_state = {
    "mode": "normal",  # normal | dating | social
    "speed_preset": "balanced",  # fast | balanced | careful
}

# Humanizer knobs (UI-configurable; presets remain Fast/Balanced/Careful)
humanizer_state: Dict[str, Any] = {
    "enabled": True,
    "delay_sigma": 0.55,
    "tap_jitter_frac": 0.22,
    "swipe_curve_amp": 0.14,
    "session_start_jitter_min": 0,
    "session_start_jitter_max": 45,
    "session_end_early_min": 0,
    "session_end_early_max": 35,
    "shuffle_apps": True,
    "shuffle_conversations": True,
    "micro_pause_chance": None,
    "long_break_chance": None,
    "idle_chance": None,
    "action_delay_min": None,
    "action_delay_max": None,
    "message_gap_min": None,
    "message_gap_max": None,
}

_needs_you_queue = None


def get_needs_you_queue(auth: Optional[dict] = None):
    """Shared Needs-you queue (Social + Dating).

    On AWS, Dynamo (`needs_you` user setting) is source of truth; /tmp JSON is
    only a read-through cache.
    """
    global _needs_you_queue
    user_id = _dating_user_id(auth) if auth is not None else "local"
    # Recreate when owner changes (multi-tenant Lambda warm reuse)
    if _needs_you_queue is not None and getattr(
        _needs_you_queue, "_user_id", None
    ) not in (None, user_id):
        _needs_you_queue = None
    if _needs_you_queue is None:
        from mobilerun.needs_you.queue import NeedsYouQueue

        path = Path("/tmp/mobilerun") / "needs_you.json"
        if os.environ.get("MOBILERUN_DATA"):
            path = Path(os.environ["MOBILERUN_DATA"]) / "needs_you.json"
        elif os.environ.get("USE_AWS_STORAGE", "").lower() not in (
            "1",
            "true",
            "yes",
        ):
            path = Path.home() / ".mobilerun" / "needs_you.json"

        remote_load = None
        remote_save = None
        if os.environ.get("USE_AWS_STORAGE", "").lower() in ("1", "true", "yes"):
            try:
                from storage import get_user_setting, save_user_setting
            except ImportError:
                from backend.storage import (  # type: ignore
                    get_user_setting,
                    save_user_setting,
                )

            uid = user_id

            def remote_load():
                return get_user_setting(uid, "needs_you")

            def remote_save(payload: Dict[str, Any]) -> None:
                save_user_setting(uid, "needs_you", payload)

        _needs_you_queue = NeedsYouQueue(
            persist_path=path, remote_load=remote_load, remote_save=remote_save
        )
        _needs_you_queue._user_id = user_id  # type: ignore[attr-defined]
    return _needs_you_queue


def _active_mode_job(kind: str, job_id: Optional[str]) -> bool:
    """True only if Dynamo still has a running/paused job for this id."""
    if not job_id:
        return False
    try:
        from storage import get_job
    except ImportError:
        from backend.storage import get_job  # type: ignore
    try:
        job = get_job(job_id)
    except Exception:
        return False
    if not job:
        return False
    if kind and str(job.get("kind") or "") not in ("", kind):
        # Allow missing kind for older rows
        if str(job.get("kind") or "") != kind:
            pass
    return str(job.get("status") or "") in ("running", "paused")


def _load_dating_runtime(auth: Optional[dict] = None) -> None:
    """Hydrate dating_mode_state prefs/review_queue from Dynamo when present."""
    try:
        from storage import get_user_setting
    except ImportError:
        from backend.storage import get_user_setting  # type: ignore

    user_id = _dating_user_id(auth)
    try:
        prefs = get_user_setting(user_id, "dating_runtime") or {}
    except Exception:
        prefs = {}
    if not isinstance(prefs, dict):
        return
    if prefs.get("speed_preset") in ("fast", "balanced", "careful"):
        dating_mode_state["speed_preset"] = prefs["speed_preset"]
    if prefs.get("opener_mode") in ("templates", "ai"):
        dating_mode_state["opener_mode"] = prefs["opener_mode"]
    if "review_before_send" in prefs:
        dating_mode_state["review_before_send"] = bool(prefs["review_before_send"])
    if isinstance(prefs.get("review_queue"), list):
        dating_mode_state["review_queue"] = list(prefs["review_queue"])
    if "running" in prefs:
        dating_mode_state["running"] = bool(prefs["running"])
    if "paused" in prefs:
        dating_mode_state["paused"] = bool(prefs["paused"])
    if prefs.get("job_id"):
        dating_mode_state["job_id"] = prefs["job_id"]
    # Reconcile stale "running" after job completed/stopped (or Lambda cold start)
    jid = dating_mode_state.get("job_id")
    if dating_mode_state.get("running") and not _active_mode_job("dating", jid):
        dating_mode_state["running"] = False
        dating_mode_state["paused"] = False
        try:
            _save_dating_runtime(auth)
        except Exception:
            pass


def _save_dating_runtime(auth: Optional[dict] = None) -> None:
    try:
        from storage import save_user_setting
    except ImportError:
        from backend.storage import save_user_setting  # type: ignore

    user_id = _dating_user_id(auth)
    save_user_setting(
        user_id,
        "dating_runtime",
        {
            "speed_preset": dating_mode_state.get("speed_preset", "balanced"),
            "opener_mode": dating_mode_state.get("opener_mode", "templates"),
            "review_before_send": dating_mode_state.get("review_before_send", True),
            "review_queue": list(dating_mode_state.get("review_queue") or []),
            "running": bool(dating_mode_state.get("running")),
            "paused": bool(dating_mode_state.get("paused")),
            "job_id": dating_mode_state.get("job_id"),
            "current_app": dating_mode_state.get("current_app"),
        },
    )


def _load_social_runtime(auth: Optional[dict] = None) -> None:
    """Hydrate social_mode_state from Dynamo so Stop works across Lambda instances."""
    try:
        from storage import get_user_setting
    except ImportError:
        from backend.storage import get_user_setting  # type: ignore
    try:
        user_id = _dating_user_id(auth)
        prefs = get_user_setting(user_id, "social_runtime") or {}
    except Exception:
        prefs = {}
    if not isinstance(prefs, dict):
        prefs = {}
    if prefs.get("job_id"):
        social_mode_state["job_id"] = prefs["job_id"]
    if "running" in prefs:
        social_mode_state["running"] = bool(prefs["running"])
    if "paused" in prefs:
        social_mode_state["paused"] = bool(prefs["paused"])
    if prefs.get("speed_preset"):
        social_mode_state["speed_preset"] = prefs["speed_preset"]
    jid = social_mode_state.get("job_id")
    if social_mode_state.get("running") and not _active_mode_job("social", jid):
        social_mode_state["running"] = False
        social_mode_state["paused"] = False
        try:
            _save_social_runtime(auth)
        except Exception:
            pass
    elif (not social_mode_state.get("running")) and _active_mode_job("social", jid):
        # Recover running flag when another Lambda started the job
        social_mode_state["running"] = True


def _save_social_runtime(auth: Optional[dict] = None) -> None:
    try:
        from storage import save_user_setting
    except ImportError:
        from backend.storage import save_user_setting  # type: ignore

    user_id = _dating_user_id(auth)
    save_user_setting(
        user_id,
        "social_runtime",
        {
            "running": bool(social_mode_state.get("running")),
            "paused": bool(social_mode_state.get("paused")),
            "job_id": social_mode_state.get("job_id"),
            "speed_preset": social_mode_state.get("speed_preset", "balanced"),
            "current_app": social_mode_state.get("current_app"),
        },
    )


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
    opener_mode: str = "templates"  # templates | ai
    # package_name -> templates | ai
    per_app_opener_mode: Optional[Dict[str, str]] = None
    # Reply persona + date flow
    reply_persona_prompt: Optional[str] = None
    invite_days_min: Optional[int] = None
    invite_days_max: Optional[int] = None
    home_location: Optional[str] = None
    radius_miles: Optional[float] = None
    invite_enabled: Optional[bool] = None
    handoff_enabled: Optional[bool] = None
    calendar_on_handoff: Optional[bool] = None
    contact_ask_enabled: Optional[bool] = None
    contact_ask_text: Optional[str] = None
    contact_ask_order: Optional[List[str]] = None
    contact_ask_whatsapp_text: Optional[str] = None
    contact_ask_snapchat_text: Optional[str] = None
    date_flow_per_app: Optional[Dict[str, Dict[str, Any]]] = None


class DateFlowEvaluateRequest(BaseModel):
    match_id: str
    package_name: str = ""
    inbound: str = ""
    distance_miles: Optional[float] = None
    her_name: str = ""
    is_opener: bool = False
    # Test hook: force chat age in days
    days_chatting: Optional[float] = None
    her_message_count: Optional[int] = None


class ComposeOpenerRequest(BaseModel):
    match_id: str
    package_name: str = ""
    profile_name: str = ""
    is_opener: bool = True
    inbound_preview: str = ""
    local_hour: Optional[int] = None
    local_minute: Optional[int] = None
    distance_miles: Optional[float] = None


class OpenerTemplateBody(BaseModel):
    id: Optional[str] = None
    text: str
    bucket: str = "any"
    enabled: bool = True


class OpenerLibraryUpdate(BaseModel):
    opener_mode: Optional[str] = None
    per_app_mode: Optional[Dict[str, str]] = None
    templates: Optional[List[OpenerTemplateBody]] = None


class AgentModeConfig(BaseModel):
    mode: str = "normal"
    speed_preset: str = "balanced"


class HumanizerUpdate(BaseModel):
    """Optional overrides on top of Fast/Balanced/Careful presets."""

    enabled: Optional[bool] = None
    delay_sigma: Optional[float] = None
    tap_jitter_frac: Optional[float] = None
    swipe_curve_amp: Optional[float] = None
    session_start_jitter_min: Optional[int] = None
    session_start_jitter_max: Optional[int] = None
    session_end_early_min: Optional[int] = None
    session_end_early_max: Optional[int] = None
    shuffle_apps: Optional[bool] = None
    shuffle_conversations: Optional[bool] = None
    micro_pause_chance: Optional[float] = None
    long_break_chance: Optional[float] = None
    idle_chance: Optional[float] = None
    action_delay_min: Optional[float] = None
    action_delay_max: Optional[float] = None
    message_gap_min: Optional[float] = None
    message_gap_max: Optional[float] = None
    speed_preset: Optional[str] = None


class SafetyCheckRequest(BaseModel):
    """Screen observation for safety auto-pause (never solves prompts)."""

    app: str = "MockDating"
    screen_text: str = ""
    ui_texts: Optional[List[str]] = None
    ui_tree: Optional[Any] = None
    llm_check: bool = False
    force_pause_all: bool = False
    screenshot_b64: Optional[str] = None
    package_name: str = ""
    device_id: Optional[str] = None


class SafetyResumeRequest(BaseModel):
    app: Optional[str] = None
    resume_all: bool = False


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
        "needs_you_badge": 0,  # Needs-you portal removed
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


@app.get("/api/humanizer")
async def get_humanizer(auth: Optional[dict] = Depends(optional_verify_token)):
    """Humanizer preset bands + UI-configurable knobs."""
    from mobilerun.agent.humanizer import HumanizerConfig, describe_presets

    preset = agent_mode_state.get("speed_preset", "balanced")
    mode = agent_mode_state.get("mode", "normal")
    cfg = HumanizerConfig.from_dict(
        {
            **{k: v for k, v in humanizer_state.items() if v is not None},
            "preset": preset,
            "mode": mode,
        }
    )
    return {
        "speed_preset": preset,
        "mode": mode,
        "config": cfg.to_public_dict(),
        "overrides": humanizer_state,
        "presets": describe_presets(),
        "notes": (
            "Delays are log-normal / non-uniform with micro-pauses and rare long "
            "breaks. No fixed intervals. Caps and Fast/Balanced/Careful still apply."
        ),
    }


@app.post("/api/humanizer")
async def update_humanizer(
    body: HumanizerUpdate, auth: Optional[dict] = Depends(optional_verify_token)
):
    """Update humanizer knobs from UI. Presets stay Fast/Balanced/Careful."""
    data = body.dict(exclude_unset=True)
    speed = data.pop("speed_preset", None)
    if speed is not None:
        speed = str(speed).lower()
        if speed not in ("fast", "balanced", "careful"):
            raise HTTPException(
                status_code=400, detail="speed_preset must be fast|balanced|careful"
            )
        agent_mode_state["speed_preset"] = speed
        dating_mode_state["speed_preset"] = speed
        social_mode_state["speed_preset"] = speed
    for k, v in data.items():
        if k in humanizer_state:
            humanizer_state[k] = v
    return await get_humanizer(auth=auth)


@app.get("/api/safety/status")
async def safety_status(auth: Optional[dict] = Depends(optional_verify_token)):
    from mobilerun.safety.runtime import get_safety_state

    st = get_safety_state().to_dict()
    st["dating_paused"] = bool(dating_mode_state.get("paused"))
    st["social_paused"] = bool(social_mode_state.get("paused"))
    return st


@app.post("/api/safety/check")
async def safety_check(
    body: SafetyCheckRequest, auth: Optional[dict] = Depends(optional_verify_token)
):
    """
    Detect on-screen warnings / verification / captcha / rate-limit / ban /
    login / selfie prompts. On hit: pause that app's loop (optionally all),
    screenshot, Needs-you + notify. Never solves or bypasses the prompt.
    """
    from mobilerun.safety.runtime import check_screen_and_pause

    q = get_needs_you_queue()
    screenshot_bytes = None
    if body.screenshot_b64:
        try:
            screenshot_bytes = base64.b64decode(body.screenshot_b64)
        except Exception:
            screenshot_bytes = None

    def _pause_dating() -> None:
        dating_mode_state["paused"] = True
        dating_mode_state["running"] = dating_mode_state.get("running", False)
        dating_mode_state["current_app"] = body.app

    def _pause_social() -> None:
        social_mode_state["paused"] = True
        social_mode_state["current_app"] = body.app

    def _push_needs_you(**kwargs) -> str:
        item = q.add(
            source="safety",
            app_name=kwargs.get("app") or body.app,
            package_name=body.package_name or "",
            conversation_id="safety",
            contact_name="Safety pause",
            inbound_preview=kwargs.get("body") or kwargs.get("reason") or "",
            draft_reply="",
            reasons=[kwargs.get("category") or "safety_pause", "needs_resume"],
            confidence=float((kwargs.get("meta") or {}).get("confidence") or 0.9),
            meta={
                "kind": "safety_pause",
                "category": kwargs.get("category"),
                "screenshot_path": kwargs.get("screenshot_path"),
                **(kwargs.get("meta") or {}),
            },
        )
        return item.id

    notified_payload: Dict[str, Any] = {}

    def _notify(**kwargs) -> None:
        notified_payload.update(kwargs)
        # Best-effort APK push + UI broadcast (sync wrappers)
        title = kwargs.get("title") or f"Needs you · {body.app}"
        nbody = kwargs.get("body") or ""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(
                    _broadcast_safety_notify(
                        body.device_id, title, nbody, kwargs.get("needs_you_id")
                    )
                )
        except Exception:
            logger.exception("safety notify schedule failed")

    result = check_screen_and_pause(
        app=body.app,
        screen_text=body.screen_text,
        ui_texts=body.ui_texts,
        ui_tree=body.ui_tree,
        llm_check=body.llm_check,
        force_pause_all=body.force_pause_all,
        push_needs_you=_push_needs_you,
        notify=_notify,
        screenshot_bytes=screenshot_bytes,
        pause_mode_callbacks={
            "dating": _pause_dating,
            "social": _pause_social,
        },
    )
    return {
        **result.to_dict(),
        "badge": q.pending_count(),
        "dating_paused": dating_mode_state.get("paused"),
        "social_paused": social_mode_state.get("paused"),
        "notify": notified_payload or None,
    }


async def _broadcast_safety_notify(
    device_id: Optional[str], title: str, body: str, needs_you_id: Optional[str]
) -> None:
    payload = {
        "type": "push_notification",
        "title": title,
        "body": body,
        "kind": "safety_pause",
        "needs_you_id": needs_you_id,
    }
    ui_payload = {
        "type": "needs_you",
        "kind": "safety_pause",
        "badge": get_needs_you_queue().pending_count(),
        "title": title,
        "body": body,
        "needs_you_id": needs_you_id,
    }
    # Fan out to UI websockets
    dead = []
    for ws in list(websocket_clients):
        try:
            await ws.send_json(ui_payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        try:
            websocket_clients.remove(ws)
        except ValueError:
            pass
    if device_id and device_id in device_websockets:
        try:
            await device_websockets[device_id].send_json(payload)
        except Exception:
            logger.warning("device notify failed for %s", device_id)


@app.post("/api/safety/resume")
async def safety_resume(
    body: SafetyResumeRequest, auth: Optional[dict] = Depends(optional_verify_token)
):
    """Resume only when Mac taps Resume — never auto-resume after a safety pause."""
    from mobilerun.safety.runtime import resume_safety

    st = resume_safety(app=body.app, resume_all=body.resume_all or not body.app)
    if st.pause_all is False and not st.paused_apps:
        dating_mode_state["paused"] = False
        social_mode_state["paused"] = False
    elif body.app and body.app not in st.paused_apps and not st.pause_all:
        # App-level resume: clear mode pause if nothing else blocked
        dating_mode_state["paused"] = False
        social_mode_state["paused"] = False
    return {
        "status": "resumed",
        "safety": st.to_dict(),
        "dating_paused": dating_mode_state.get("paused"),
        "social_paused": social_mode_state.get("paused"),
    }


def _dating_user_id(auth: Optional[dict]) -> str:
    return _owner_key(auth) or "local"


def _load_opener_library(auth: Optional[dict] = None):
    from mobilerun.dating.openers import load_default_library, merge_with_defaults

    user_id = _dating_user_id(auth)
    user_data = None
    try:
        from storage import get_user_setting
    except ImportError:
        from backend.storage import get_user_setting  # type: ignore

    try:
        user_data = get_user_setting(user_id, "dating_openers")
    except Exception:
        logger.exception("load dating_openers failed")
    # Prefer in-memory overrides from this process
    mem = dating_mode_state.get("opener_library")
    if isinstance(mem, dict) and mem.get("templates"):
        user_data = mem
    return merge_with_defaults(user_data), user_id


def _save_opener_library(lib, auth: Optional[dict] = None) -> None:
    try:
        from storage import save_user_setting
    except ImportError:
        from backend.storage import save_user_setting  # type: ignore

    user_id = _dating_user_id(auth)
    data = lib.to_dict()
    dating_mode_state["opener_library"] = data
    dating_mode_state["opener_mode"] = lib.opener_mode
    save_user_setting(user_id, "dating_openers", data)


_date_flow_mgr = None


def _load_date_flow(auth: Optional[dict] = None):
    """Load DateFlowManager (config from settings + persisted chat state)."""
    global _date_flow_mgr
    from pathlib import Path as _Path

    from mobilerun.dating.date_flow import (
        DateFlowConfig,
        DateFlowManager,
        default_persist_path,
    )

    user_id = _dating_user_id(auth)
    stored = None
    try:
        from storage import get_user_setting
    except ImportError:
        from backend.storage import get_user_setting  # type: ignore
    try:
        stored = get_user_setting(user_id, "dating_date_flow")
    except Exception:
        logger.exception("load dating_date_flow failed")
    mem = dating_mode_state.get("date_flow")
    raw = mem or stored or {}
    cfg = DateFlowConfig.from_dict(
        raw.get("config") if isinstance(raw, dict) and "config" in raw else raw
    )

    def _push(**kwargs) -> str:
        # Needs-you portal removed — date-flow handoffs no longer enqueue UI items.
        logger.info(
            "date-flow handoff (no needs-you): kind=%s app=%s",
            kwargs.get("kind"),
            kwargs.get("app"),
        )
        return ""

    persist = default_persist_path()
    if os.environ.get("MOBILERUN_DATA"):
        persist = _Path(os.environ["MOBILERUN_DATA"]) / "dating_date_flow.json"
    if _date_flow_mgr is None or getattr(_date_flow_mgr, "_user_id", None) != user_id:
        _date_flow_mgr = DateFlowManager(
            config=cfg,
            persist_path=persist,
            push_needs_you=_push,
            on_match_upsert=None,  # Matches CRM removed
        )
        _date_flow_mgr._user_id = user_id  # type: ignore[attr-defined]
    else:
        _date_flow_mgr.config = cfg
        _date_flow_mgr.push_needs_you = _push
        _date_flow_mgr.on_match_upsert = None
    return _date_flow_mgr


def _save_date_flow(mgr, auth: Optional[dict] = None) -> None:
    try:
        from storage import save_user_setting
    except ImportError:
        from backend.storage import save_user_setting  # type: ignore

    user_id = _dating_user_id(auth)
    data = {
        "config": mgr.config.to_dict(),
        "stats": mgr.stats_summary(),
    }
    dating_mode_state["date_flow"] = data
    save_user_setting(user_id, "dating_date_flow", data)
    mgr._persist()


@app.get("/api/dating/config")
async def get_dating_config(auth: Optional[dict] = Depends(optional_verify_token)):
    """Get dating mode configuration."""
    from mobilerun.dating.config import (
        DatingModeConfig as ConfigModel,
        display_name_for_package,
        ensure_default_apps,
    )

    _load_dating_runtime(auth)
    config = ConfigModel()
    # r51b: always include newly runnable default apps; never drop saved rows
    config.apps = ensure_default_apps(getattr(config, "apps", None))
    lib, _ = _load_opener_library(auth)
    df = _load_date_flow(auth)
    opener_mode = (
        dating_mode_state.get("opener_mode")
        or lib.opener_mode
        or getattr(config, "opener_mode", "templates")
    )
    return {
        "apps": [
            {
                "name": display_name_for_package(app.package_name, app.name),
                "package_name": app.package_name,
                "enabled": app.enabled,
                "daily_swipe_cap": app.daily_swipe_cap,
                "daily_reply_cap": app.daily_reply_cap,
                "daily_opener_target_min": app.daily_opener_target_min,
                "daily_opener_target_max": app.daily_opener_target_max,
                "opener_mode": lib.per_app_mode.get(app.package_name) or opener_mode,
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
        "opener_mode": opener_mode,
        "per_app_opener_mode": lib.per_app_mode,
        "date_flow": df.config.to_dict(),
        "date_flow_stats": df.stats_summary(),
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
    mode = (config.opener_mode or "templates").lower()
    if mode not in ("templates", "ai"):
        raise HTTPException(status_code=400, detail="opener_mode must be templates|ai")
    dating_mode_state["opener_mode"] = mode
    lib, _ = _load_opener_library(auth)
    lib.opener_mode = mode
    if config.per_app_opener_mode is not None:
        cleaned = {}
        for k, v in config.per_app_opener_mode.items():
            vv = str(v).lower()
            if vv in ("templates", "ai"):
                cleaned[k] = vv
        lib.per_app_mode = cleaned
    _save_opener_library(lib, auth)

    # Reply persona + date flow
    from mobilerun.dating.date_flow import DateFlowConfig

    mgr = _load_date_flow(auth)
    cur = mgr.config.to_dict()
    dump = config.dict() if hasattr(config, "dict") else config.model_dump()
    for key in (
        "reply_persona_prompt",
        "invite_days_min",
        "invite_days_max",
        "home_location",
        "radius_miles",
        "invite_enabled",
        "handoff_enabled",
        "calendar_on_handoff",
        "contact_ask_enabled",
        "contact_ask_text",
        "contact_ask_order",
        "contact_ask_whatsapp_text",
        "contact_ask_snapchat_text",
    ):
        if dump.get(key) is not None:
            cur[key] = dump[key]
    if dump.get("date_flow_per_app") is not None:
        cur["per_app"] = dump["date_flow_per_app"]
    mgr.config = DateFlowConfig.from_dict(cur)
    _save_date_flow(mgr, auth)
    if dump.get("review_before_send") is not None:
        dating_mode_state["review_before_send"] = bool(dump["review_before_send"])
    _save_dating_runtime(auth)

    payload = dump
    payload["date_flow"] = mgr.config.to_dict()
    return {"status": "success", "config": payload}


@app.get("/api/dating/openers")
async def get_dating_openers(auth: Optional[dict] = Depends(optional_verify_token)):
    """Template opener library (file defaults + per-user DynamoDB/local overrides)."""
    from mobilerun.dating.openers import (
        bucket_for_local_time,
        summarize_buckets,
        validate_active_bounds,
    )

    lib, user_id = _load_opener_library(auth)
    ok, msg = validate_active_bounds(lib)
    return {
        "user_id": user_id,
        "library": lib.to_dict(),
        "bucket_now": bucket_for_local_time(),
        "bucket_counts": summarize_buckets(lib),
        "active_ok": ok,
        "active_message": msg,
        "min_active": lib.min_active,
        "max_active": lib.max_active,
    }


@app.post("/api/dating/openers")
async def update_dating_openers(
    body: OpenerLibraryUpdate, auth: Optional[dict] = Depends(optional_verify_token)
):
    """Replace/update opener library (add/edit/enable via full templates list)."""
    import secrets as _secrets

    from mobilerun.dating.openers import (
        OpenerTemplate,
        validate_active_bounds,
    )

    lib, _ = _load_opener_library(auth)
    if body.opener_mode is not None:
        mode = body.opener_mode.lower()
        if mode not in ("templates", "ai"):
            raise HTTPException(
                status_code=400, detail="opener_mode must be templates|ai"
            )
        lib.opener_mode = mode
        dating_mode_state["opener_mode"] = mode
    if body.per_app_mode is not None:
        cleaned = {}
        for k, v in body.per_app_mode.items():
            vv = str(v).lower()
            if vv in ("templates", "ai"):
                cleaned[k] = vv
        lib.per_app_mode = cleaned
    if body.templates is not None:
        new_tmpls = []
        for t in body.templates:
            tid = (t.id or "").strip() or f"t_{_secrets.token_hex(3)}"
            text = (t.text or "").strip()
            if not text:
                continue
            new_tmpls.append(
                OpenerTemplate(
                    id=tid,
                    text=text,
                    bucket=(t.bucket or "any").lower(),
                    enabled=bool(t.enabled),
                )
            )
        lib.templates = new_tmpls
    ok, msg = validate_active_bounds(lib)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    _save_opener_library(lib, auth)
    return {"status": "ok", "library": lib.to_dict(), "active_ok": ok}


@app.post("/api/dating/openers/template")
async def upsert_opener_template(
    body: OpenerTemplateBody, auth: Optional[dict] = Depends(optional_verify_token)
):
    """Add or edit a single template."""
    import secrets as _secrets

    from mobilerun.dating.openers import OpenerTemplate, validate_active_bounds

    lib, _ = _load_opener_library(auth)
    tid = (body.id or "").strip() or f"t_{_secrets.token_hex(3)}"
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text required")
    lib.set_template(
        OpenerTemplate(
            id=tid,
            text=text,
            bucket=(body.bucket or "any").lower(),
            enabled=bool(body.enabled),
        )
    )
    ok, msg = validate_active_bounds(lib)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    _save_opener_library(lib, auth)
    return {"status": "ok", "id": tid, "library": lib.to_dict()}


@app.delete("/api/dating/openers/template/{template_id}")
async def delete_opener_template(
    template_id: str, auth: Optional[dict] = Depends(optional_verify_token)
):
    from mobilerun.dating.openers import validate_active_bounds

    lib, _ = _load_opener_library(auth)
    if not lib.delete_template(template_id):
        raise HTTPException(status_code=404, detail="template not found")
    ok, msg = validate_active_bounds(lib)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    _save_opener_library(lib, auth)
    return {"status": "deleted", "id": template_id, "library": lib.to_dict()}


@app.post("/api/dating/compose")
async def compose_dating_message_api(
    body: ComposeOpenerRequest, auth: Optional[dict] = Depends(optional_verify_token)
):
    """Compose opener (template or AI) or reply (AI + date-flow / handoff)."""
    from datetime import datetime as _dt

    from mobilerun.dating.persona import PersonaManager

    # Honour safety pause — never send while blocked
    try:
        from mobilerun.safety.runtime import get_safety_state

        if get_safety_state().is_paused(body.package_name or None):
            raise HTTPException(
                status_code=409, detail="Safety pause active — resume in UI first"
            )
    except HTTPException:
        raise
    except Exception:
        pass

    if dating_mode_state.get("paused"):
        raise HTTPException(
            status_code=409, detail="Dating mode paused — resume before composing"
        )

    lib, _ = _load_opener_library(auth)
    mgr = _load_date_flow(auth)
    now = None
    if body.local_hour is not None:
        now = _dt.now().replace(
            hour=int(body.local_hour) % 24,
            minute=int(body.local_minute or 0) % 60,
            second=0,
            microsecond=0,
        )

    ai_calls = {"n": 0}

    def ai_callable(**kwargs):
        ai_calls["n"] += 1
        if kwargs.get("is_opener"):
            return f"[AI opener for {kwargs.get('profile_name') or 'match'}]"
        return f"[AI reply to: {(kwargs.get('inbound_preview') or '')[:40]}]"

    persona = PersonaManager(
        opener_library=lib,
        ai_callable=ai_callable,
        date_flow=mgr,
        reply_persona_prompt=mgr.config.for_app(body.package_name).reply_persona_prompt,
    )
    try:
        result = persona.compose(
            is_opener=body.is_opener,
            match_id=body.match_id,
            package_name=body.package_name,
            profile_name=body.profile_name or "",
            inbound_preview=body.inbound_preview,
            now=now,
            distance_miles=body.distance_miles,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if result.get("source") == "template":
        _save_opener_library(lib, auth)
    _save_date_flow(mgr, auth)

    return {
        **result,
        "ai_calls": ai_calls["n"],
        "opener_mode": lib.mode_for_app(body.package_name),
        "date_flow_stats": mgr.stats_summary(),
    }


@app.get("/api/dating/date-flow")
async def get_date_flow(auth: Optional[dict] = Depends(optional_verify_token)):
    """Reply persona + date-invite settings and stats."""
    mgr = _load_date_flow(auth)
    return {"config": mgr.config.to_dict(), "stats": mgr.stats_summary()}


@app.post("/api/dating/date-flow")
async def update_date_flow(
    body: Dict[str, Any], auth: Optional[dict] = Depends(optional_verify_token)
):
    """Update global / per-app reply persona + date-flow settings."""
    from mobilerun.dating.date_flow import DateFlowConfig

    mgr = _load_date_flow(auth)
    cur = mgr.config.to_dict()
    incoming = body.get("config") if isinstance(body.get("config"), dict) else body
    for k, v in (incoming or {}).items():
        if k in cur and v is not None:
            cur[k] = v
    if "per_app" in (incoming or {}) and incoming["per_app"] is not None:
        cur["per_app"] = incoming["per_app"]
    mgr.config = DateFlowConfig.from_dict(cur)
    _save_date_flow(mgr, auth)
    return {
        "status": "success",
        "config": mgr.config.to_dict(),
        "stats": mgr.stats_summary(),
    }


@app.post("/api/dating/date-flow/evaluate")
async def evaluate_date_flow(
    body: DateFlowEvaluateRequest,
    auth: Optional[dict] = Depends(optional_verify_token),
):
    """Evaluate invite timing / radius / handoff for a chat turn (testable)."""
    from datetime import datetime as _dt
    from datetime import timedelta

    mgr = _load_date_flow(auth)
    chat = mgr.get_chat(body.match_id, body.package_name)
    if body.days_chatting is not None:
        chat.chat_started_at = (
            _dt.now() - timedelta(days=float(body.days_chatting))
        ).isoformat()
    if body.her_message_count is not None:
        chat.her_message_count = max(0, int(body.her_message_count) - 1)
    decision = mgr.evaluate_turn(
        match_id=body.match_id,
        package_name=body.package_name,
        inbound=body.inbound,
        distance_miles=body.distance_miles,
        her_name=body.her_name,
        is_opener=body.is_opener,
    )
    _save_date_flow(mgr, auth)
    return {
        **decision.to_dict(),
        "stats": mgr.stats_summary(),
        "invite_threshold_days": mgr.invite_threshold_for(
            body.match_id, body.package_name
        ),
    }


@app.api_route("/api/dating/matches", methods=["GET", "POST"])
@app.api_route("/api/dating/matches/{match_id}", methods=["PUT", "DELETE"])
@app.get("/api/dating/matches/export.csv")
async def dating_matches_removed(match_id: str = ""):
    """Matches CRM removed — MacMobileRun does not track matches."""
    raise HTTPException(
        status_code=410,
        detail="Matches tracking removed from MacMobileRun",
    )


# === Selector discovery + cache (dating/social nav, a11y-first) ===

_selector_nav = None


def get_selector_navigator(auth: Optional[dict] = None):
    global _selector_nav
    from mobilerun.selectors.cache import SelectorCache
    from mobilerun.selectors.navigator import SelectorNavigator

    user_id = _dating_user_id(auth)

    def _push(**kwargs) -> str:
        q = get_needs_you_queue()
        item = q.add(
            source="safety",
            app_name=kwargs.get("app") or "unknown",
            package_name=kwargs.get("app") or "",
            conversation_id="selector",
            contact_name="Selector rediscovery",
            inbound_preview=kwargs.get("body") or kwargs.get("reason") or "",
            draft_reply="",
            reasons=["selector_discovery", "needs_resume"],
            confidence=0.9,
            meta=kwargs.get("meta") or {"kind": kwargs.get("kind")},
        )
        return item.id

    if (
        _selector_nav is None
        or getattr(_selector_nav.cache, "user_id", None) != user_id
    ):
        cache = SelectorCache(user_id=user_id, max_rediscovery=3)
        _selector_nav = SelectorNavigator(
            cache=cache,
            max_rediscovery=3,
            max_layout_variants=cache.max_layout_variants,
            push_needs_you=_push,
        )
    return _selector_nav


class SelectorResolveRequest(BaseModel):
    role: str
    package_name: str
    version_code: str = "1"
    tree: Any = None
    screenshot_b64: Optional[str] = None
    allow_llm: bool = True
    # Test hook: inline LLM JSON response (avoids real model in CI)
    llm_stub: Optional[Dict[str, Any]] = None
    # E2E/CI: simulate bounded scroll exploration without a device gesture loop.
    # initial_tree lacks the target; revealed_tree contains it after N scrolls
    # in reveal_direction (down|up|left|right).
    explore_sim: Optional[Dict[str, Any]] = None


@app.get("/api/selectors/status")
async def selectors_status(
    package_name: Optional[str] = None,
    version_code: str = "1",
    auth: Optional[dict] = Depends(optional_verify_token),
):
    """Cache status per app: last discovered, version, LLM calls used."""
    try:
        nav = get_selector_navigator(auth)
        if package_name:
            return {"apps": [nav.cache.status(package_name, version_code).to_dict()]}
        return {"apps": [s.to_dict() for s in nav.cache.list_packages()]}
    except Exception as e:
        logger.exception("selectors_status failed: %s", e)
        return {"apps": [], "error": str(e)}


@app.post("/api/selectors/resolve")
async def selectors_resolve(
    body: SelectorResolveRequest, auth: Optional[dict] = Depends(optional_verify_token)
):
    """
    Resolve a dating/social nav role via cached a11y selector (no LLM),
    falling back ONCE to LLM discovery when missing/broken.
    Supports explore_sim for scroll-off-screen rediscovery tests.
    """
    nav = get_selector_navigator(auth)
    llm_calls_box = {"n": 0}

    def llm_callable(**kwargs):
        llm_calls_box["n"] += 1
        if body.llm_stub is not None:
            return body.llm_stub
        # Soft default for tests without stub: refuse (caller may supply stub)
        return {}

    get_tree = None
    perform_scroll = None
    perform_tap_tab = None
    tree = body.tree or []
    if body.explore_sim:
        sim = body.explore_sim
        initial = sim.get("initial_tree") or tree or {"children": []}
        revealed = sim.get("revealed_tree") or tree or initial
        reveal_dir = str(sim.get("reveal_direction") or "down")
        reveal_after = int(sim.get("reveal_after") or 2)
        tap_reveal = sim.get("tap_tab")  # optional tab text that reveals
        state = {"tree": initial, "counts": {}}

        def get_tree():
            return state["tree"]

        def perform_scroll(step):
            d = getattr(step, "direction", None) or "down"
            state["counts"][d] = int(state["counts"].get(d) or 0) + 1
            if d == reveal_dir and state["counts"][d] >= reveal_after:
                state["tree"] = revealed

        def perform_tap_tab(tab: str):
            if tap_reveal and tab == tap_reveal:
                state["tree"] = revealed

        tree = initial

    result = nav.resolve(
        role=body.role,
        package_name=body.package_name,
        version_code=body.version_code,
        tree=tree,
        screenshot_b64=body.screenshot_b64,
        llm_callable=llm_callable if body.allow_llm else None,
        allow_llm=body.allow_llm,
        get_tree=get_tree,
        perform_scroll=perform_scroll,
        perform_tap_tab=perform_tap_tab,
        explore=True,
    )
    st = nav.cache.status(body.package_name, body.version_code)
    return {
        **result.to_dict(),
        "status": st.to_dict(),
        "llm_callable_invocations": llm_calls_box["n"],
    }


@app.post("/api/selectors/invalidate")
async def selectors_invalidate(
    package_name: str,
    version_code: str = "1",
    role: Optional[str] = None,
    auth: Optional[dict] = Depends(optional_verify_token),
):
    nav = get_selector_navigator(auth)
    nav.cache.invalidate(package_name, version_code, role=role)
    return {
        "status": "invalidated",
        "package_name": package_name,
        "version_code": version_code,
        "role": role,
    }


@app.get("/api/dating/stats")
async def get_dating_stats(auth: Optional[dict] = Depends(optional_verify_token)):
    """Get dating mode statistics (Europe/London day; durable per-user store).

    Also lifts Today totals from recent live dating_run jobs so the Working
    cards never show 0 when the bot already completed sends/likes tonight
    (covers missed step-sync and Tagged's tagged_fixed counter).
    """
    try:
        from dating_stats_io import (
            load_dating_stats,
            merge_recent_dating_jobs_into_stats,
            save_dating_stats,
        )
    except ImportError:
        from backend.dating_stats_io import (  # type: ignore
            load_dating_stats,
            merge_recent_dating_jobs_into_stats,
            save_dating_stats,
        )

    uid = _dating_user_id(auth)
    stats = load_dating_stats(uid)
    try:
        try:
            from storage import list_recent_jobs
        except ImportError:
            from backend.storage import list_recent_jobs  # type: ignore

        jobs = list_recent_jobs(80)
        if merge_recent_dating_jobs_into_stats(stats, jobs, user_id=uid):
            save_dating_stats(stats, uid)
    except Exception:
        logger.exception("dating stats merge from recent jobs failed")
    return stats.get_summary()


class ModeStartBody(BaseModel):
    device_id: Optional[str] = None
    dry_run: bool = True
    # live_test: real likes (capped) + message-bank sends; never super-like/paid
    live_test: bool = False
    live_test_max_n: int = 3
    stand_in_package: Optional[str] = None
    max_steps: Optional[int] = None
    # new = openers/first contact only; existing = replies only; both = default mix
    contact_scope: Optional[str] = "both"
    # Real per-app run (Run page Start / per-app Run). Packages or app keys,
    # run one after another. None = legacy stand-in loop (emulator tests).
    apps: Optional[List[str]] = None
    # Messages / swipes per app. Hinge uses it as-is; Hily caps at 5, FB at 50.
    count: Optional[int] = None
    # r43: per-app per-run numbers from each app card (package -> n). Saved
    # per user; when omitted, the saved numbers are used.
    counts: Optional[Dict[str, int]] = None
    # r45: per-app run mode (Tagged: "swipe" | "message")
    modes: Optional[Dict[str, str]] = None
    # r46: max likes per app mode ({"com.hily.app:likes": 40})
    like_caps: Optional[Dict[str, int]] = None


class RunCountsBody(BaseModel):
    counts: Dict[str, int] = {}
    # r45: per-app run mode, e.g. {"com.taggedapp": "message"}
    modes: Optional[Dict[str, str]] = None
    # r46: max likes per app mode, e.g. {"com.hily.app:likes": 40}
    like_caps: Optional[Dict[str, int]] = None


def _load_run_counts(auth: Optional[dict]) -> Dict[str, int]:
    try:
        from storage import get_user_setting
    except ImportError:
        from backend.storage import get_user_setting  # type: ignore
    try:
        from dating_run import clean_counts
    except ImportError:
        from backend.dating_run import clean_counts  # type: ignore
    try:
        data = get_user_setting(_dating_user_id(auth), "dating_run_counts") or {}
    except Exception as e:  # pragma: no cover
        logger.warning("run counts load failed: %s", e)
        data = {}
    return clean_counts(data.get("counts") if isinstance(data, dict) else None)


def _save_run_counts(auth: Optional[dict], counts: Dict[str, Any]) -> Dict[str, int]:
    try:
        from storage import save_user_setting
    except ImportError:
        from backend.storage import save_user_setting  # type: ignore
    try:
        from dating_run import clean_counts
    except ImportError:
        from backend.dating_run import clean_counts  # type: ignore
    merged = _load_run_counts(auth)
    merged.update(clean_counts(counts))
    save_user_setting(
        _dating_user_id(auth),
        "dating_run_counts",
        {
            "counts": merged,
            "modes": _load_run_modes(auth),
            "like_caps": _load_like_caps(auth),
        },
    )
    return merged


def _load_run_modes(auth: Optional[dict]) -> Dict[str, str]:
    """r45: saved per-app run modes (Tagged: swipe | message)."""
    try:
        from storage import get_user_setting
    except ImportError:
        from backend.storage import get_user_setting  # type: ignore
    try:
        from dating_run import clean_modes
    except ImportError:
        from backend.dating_run import clean_modes  # type: ignore
    try:
        data = get_user_setting(_dating_user_id(auth), "dating_run_counts") or {}
    except Exception:  # pragma: no cover
        data = {}
    return clean_modes(data.get("modes") if isinstance(data, dict) else None)


def _save_run_modes(auth: Optional[dict], modes: Optional[Dict[str, Any]]) -> Dict[str, str]:
    try:
        from storage import save_user_setting
    except ImportError:
        from backend.storage import save_user_setting  # type: ignore
    try:
        from dating_run import clean_modes
    except ImportError:
        from backend.dating_run import clean_modes  # type: ignore
    merged = _load_run_modes(auth)
    merged.update(clean_modes(modes))
    save_user_setting(
        _dating_user_id(auth),
        "dating_run_counts",
        {
            "counts": _load_run_counts(auth),
            "modes": merged,
            "like_caps": _load_like_caps(auth),
        },
    )
    return merged


def _load_like_caps(auth: Optional[dict]) -> Dict[str, int]:
    """r46: max likes per app mode, e.g. {"com.hily.app:likes": 40}."""
    try:
        from storage import get_user_setting
    except ImportError:
        from backend.storage import get_user_setting  # type: ignore
    try:
        from dating_run import clean_like_caps
    except ImportError:
        from backend.dating_run import clean_like_caps  # type: ignore
    try:
        data = get_user_setting(_dating_user_id(auth), "dating_run_counts") or {}
    except Exception:  # pragma: no cover
        data = {}
    return clean_like_caps(data.get("like_caps") if isinstance(data, dict) else None)


def _save_like_caps(
    auth: Optional[dict], caps: Optional[Dict[str, Any]]
) -> Dict[str, int]:
    try:
        from storage import save_user_setting
    except ImportError:
        from backend.storage import save_user_setting  # type: ignore
    try:
        from dating_run import clean_like_caps
    except ImportError:
        from backend.dating_run import clean_like_caps  # type: ignore
    merged = _load_like_caps(auth)
    merged.update(clean_like_caps(caps))
    save_user_setting(
        _dating_user_id(auth),
        "dating_run_counts",
        {
            "counts": _load_run_counts(auth),
            "modes": _load_run_modes(auth),
            "like_caps": merged,
        },
    )
    return merged


class DatingScheduleBody(BaseModel):
    name: Optional[str] = None
    enabled: Optional[bool] = None
    # [{"app": package or key, "runs": times per fire, "count": per run}]
    items: Optional[List[Dict[str, Any]]] = None
    time: Optional[str] = None  # HH:MM Europe/London
    days: Optional[List[int]] = None  # Mon=0 … Sun=6; [] = every day
    dry_run: Optional[bool] = None
    device_id: Optional[str] = None


def _sched_mod():
    try:
        import dating_schedule as ds  # type: ignore
    except ImportError:
        from backend import dating_schedule as ds  # type: ignore
    return ds


def _sched_body(body: DatingScheduleBody) -> Dict[str, Any]:
    dump = body.dict() if hasattr(body, "dict") else body.model_dump()
    return {k: v for k, v in dump.items() if v is not None}


@app.get("/api/dating/schedules")
async def list_dating_schedules(auth: Optional[dict] = Depends(optional_verify_token)):
    """r44: per-app / combo dating run schedules with next run (London)."""
    ds = _sched_mod()
    return {
        "schedules": [ds.with_next(s) for s in ds.load_all()],
        "timezone": "Europe/London",
    }


@app.post("/api/dating/schedules")
async def create_dating_schedule(
    body: DatingScheduleBody, auth: Optional[dict] = Depends(optional_verify_token)
):
    ds = _sched_mod()
    raw = _sched_body(body)
    raw["owner"] = _dating_user_id(auth)
    try:
        sch = ds.normalize(raw)
    except ds.ScheduleError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    all_s = ds.load_all()
    if len(all_s) >= ds.MAX_SCHEDULES:
        raise HTTPException(status_code=400, detail="Too many schedules")
    all_s.append(sch)
    ds.save_all(all_s)
    return {"status": "created", "schedule": ds.with_next(sch)}


@app.put("/api/dating/schedules/{schedule_id}")
async def update_dating_schedule(
    schedule_id: str,
    body: DatingScheduleBody,
    auth: Optional[dict] = Depends(optional_verify_token),
):
    ds = _sched_mod()
    all_s = ds.load_all()
    for i, cur in enumerate(all_s):
        if cur.get("id") == schedule_id:
            try:
                all_s[i] = ds.normalize(_sched_body(body), existing=cur)
            except ds.ScheduleError as e:
                raise HTTPException(status_code=400, detail=str(e)) from e
            ds.save_all(all_s)
            return {"status": "updated", "schedule": ds.with_next(all_s[i])}
    raise HTTPException(status_code=404, detail="Schedule not found")


@app.delete("/api/dating/schedules/{schedule_id}")
async def delete_dating_schedule(
    schedule_id: str, auth: Optional[dict] = Depends(optional_verify_token)
):
    ds = _sched_mod()
    all_s = ds.load_all()
    keep = [s for s in all_s if s.get("id") != schedule_id]
    if len(keep) == len(all_s):
        raise HTTPException(status_code=404, detail="Schedule not found")
    ds.save_all(keep)
    return {"status": "deleted", "id": schedule_id}


@app.get("/api/dating/run-counts")
async def get_run_counts(auth: Optional[dict] = Depends(optional_verify_token)):
    """Per-app per-run numbers shown on each dating app card."""
    return {
        "counts": _load_run_counts(auth),
        "modes": _load_run_modes(auth),
        "like_caps": _load_like_caps(auth),
    }


@app.post("/api/dating/run-counts")
async def set_run_counts(
    body: RunCountsBody, auth: Optional[dict] = Depends(optional_verify_token)
):
    counts = _save_run_counts(auth, body.counts) if body.counts else _load_run_counts(auth)
    modes = _save_run_modes(auth, body.modes) if body.modes else _load_run_modes(auth)
    caps = (
        _save_like_caps(auth, body.like_caps)
        if body.like_caps
        else _load_like_caps(auth)
    )
    return {"status": "saved", "counts": counts, "modes": modes, "like_caps": caps}


def _kick_job(job_id: str) -> None:
    step_arn = os.environ.get("STEP_WORKER_ARN")
    if step_arn and os.environ.get("USE_AWS_STORAGE") == "true":
        import boto3

        boto3.client("lambda").invoke(
            FunctionName=step_arn,
            InvocationType="Event",
            Payload=json.dumps({"job_id": job_id}).encode(),
        )


def _activity_for_mode(kind: str, job_id: Optional[str] = None) -> Dict[str, Any]:
    try:
        from activity_log import activity_payload_from_job
    except ImportError:
        from backend.activity_log import activity_payload_from_job  # type: ignore
    try:
        from storage import get_job, list_recent_jobs
    except ImportError:
        from backend.storage import get_job, list_recent_jobs  # type: ignore

    job = None
    if job_id:
        try:
            job = get_job(job_id)
        except Exception:
            job = None
    if job and job.get("dating_run") and job_id:
        # Multi-app run: show the app that is on now (newest job of the run)
        try:
            try:
                from dating_run import latest_in_run
            except ImportError:
                from backend.dating_run import latest_in_run  # type: ignore
            job = latest_in_run(job_id, list_recent_jobs(limit=40)) or job
        except Exception:
            pass
    if not job:
        try:
            for j in list_recent_jobs(limit=40):
                if str(j.get("kind") or "") == kind:
                    job = j
                    break
        except Exception:
            job = None
    return activity_payload_from_job(job)


async def _start_dating_apps_run(
    body: ModeStartBody, auth: Optional[dict], device_id: str, dry_run: bool
) -> Dict[str, Any]:
    """Run-page Start / per-app Run: real agent jobs, one app at a time."""
    try:
        from dating_run import build_job, split_supported
    except ImportError:
        from backend.dating_run import build_job, split_supported  # type: ignore
    try:
        from device_push import device_is_reachable
    except ImportError:
        try:
            from backend.device_push import device_is_reachable  # type: ignore
        except ImportError:
            device_is_reachable = lambda _d: False  # type: ignore
    try:
        from storage import put_job
    except ImportError:
        from backend.storage import put_job  # type: ignore

    queue, unsupported = split_supported(list(body.apps or []))
    if not queue:
        names = ", ".join(unsupported) or "none selected"
        raise HTTPException(
            status_code=400,
            detail=f"No app with an auto run selected ({names}). "
            "Supported: Hinge, Hily, Facebook Dating, Yubo, Bumble, Badoo, Tagged, Taimi, BLK, Tinder, Boo, Breeze, Pure, 3Fun.",
        )
    did = (device_id or "").strip()
    if not did or did == "default":
        raise HTTPException(
            status_code=400, detail="Pick your phone in the device list first"
        )
    mem = connected_devices.get(did) or {}
    if not (mem.get("connected") or device_is_reachable(did)):
        raise HTTPException(
            status_code=400,
            detail="Phone offline — open MobileRun on the phone and wait "
            "until Devices shows Connected",
        )
    # Each app card's own number; fall back to the saved per-app numbers.
    try:
        counts = (
            _save_run_counts(auth, body.counts)
            if body.counts
            else _load_run_counts(auth)
        )
    except Exception as e:
        logger.warning("run counts save/load failed: %s", e)
        counts = dict(body.counts or {})
    try:
        modes = (
            _save_run_modes(auth, body.modes)
            if getattr(body, "modes", None)
            else _load_run_modes(auth)
        )
    except Exception as e:
        logger.warning("run modes save/load failed: %s", e)
        modes = dict(getattr(body, "modes", None) or {})
    try:
        like_caps = (
            _save_like_caps(auth, body.like_caps)
            if getattr(body, "like_caps", None)
            else _load_like_caps(auth)
        )
    except Exception as e:
        logger.warning("like caps save/load failed: %s", e)
        like_caps = dict(getattr(body, "like_caps", None) or {})
    job = build_job(
        device_id=did,
        queue=queue,
        count=body.count,
        dry_run=dry_run,
        speed_preset=dating_mode_state.get("speed_preset") or "balanced",
        counts=counts,
        modes=modes,
        like_caps=like_caps,
    )
    # Owner key so agent steps can write Today totals to the right stats blob.
    job["user_id"] = _dating_user_id(auth)
    job["owner"] = job["user_id"]
    # First-contact only — do not spend steps checking existing-chat replies.
    job["contact_scope"] = "new"
    try:
        put_job(job)
        _kick_job(job["job_id"])
    except Exception as e:
        logger.exception("Could not start dating run: %s", e)
        raise HTTPException(
            status_code=503, detail=f"Could not start run: {e}"
        ) from e
    dating_mode_state["running"] = True
    dating_mode_state["paused"] = False
    dating_mode_state["job_id"] = job["job_id"]
    dating_mode_state["current_app"] = queue[0]
    _save_dating_runtime(auth)
    return {
        "status": "started",
        "state": dating_mode_state,
        "job": job,
        "queue": queue,
        "skipped": unsupported,
        "activity": _activity_for_mode("dating", job["job_id"]),
    }


@app.post("/api/dating/start")
async def start_dating_mode(
    body: Optional[ModeStartBody] = None,
    auth: Optional[dict] = Depends(optional_verify_token),
    device_id: str = "default",
    dry_run: bool = True,
    stand_in_package: Optional[str] = None,
):
    """
    Start dating mode as a step-driven cloud job (EventBridge ticks).
    Safe for Lambda — does not hold a long loop in one invocation.
    Defaults to dry_run=True so no real likes/messages are sent.
    """
    _load_dating_runtime(auth)
    existing = dating_mode_state.get("job_id")
    if dating_mode_state.get("running") and _active_mode_job("dating", existing):
        raise HTTPException(status_code=400, detail="Dating mode already running")
    # Stale in-memory flag after Lambda reuse / stopped job — allow restart
    dating_mode_state["running"] = False
    dating_mode_state.pop("job_id", None)

    contact_scope = "both"
    live_test = False
    live_test_max_n = 3
    if body:
        device_id = body.device_id or device_id
        dry_run = body.dry_run if body.dry_run is not None else dry_run
        live_test = bool(getattr(body, "live_test", False))
        live_test_max_n = int(getattr(body, "live_test_max_n", None) or 3)
        stand_in_package = body.stand_in_package or stand_in_package
        raw_scope = str(body.contact_scope or "both").lower().strip()
        if raw_scope in ("new", "existing", "both"):
            contact_scope = raw_scope
    if live_test:
        dry_run = False  # real likes/sends under caps

    if body and body.apps is not None:
        return await _start_dating_apps_run(body, auth, device_id, dry_run)

    dating_mode_state["running"] = True
    dating_mode_state["paused"] = False
    dating_mode_state["contact_scope"] = contact_scope

    job_id = f"dating_{secrets.token_hex(8)}"
    dating_mode_state["job_id"] = job_id
    # Cap dry-run / live-test jobs so emulator E2E finishes quickly
    caps = {
        "opener_target": (
            live_test_max_n
            if live_test
            else (3 if dry_run else secrets.randbelow(51) + 50)
        ),
        "global_message_max": (
            live_test_max_n
            if live_test
            else (6 if dry_run else secrets.randbelow(401) + 100)
        ),
        "swipe_cap": (
            live_test_max_n if live_test else (2 if dry_run else 50)
        ),
        "reply_cap": (
            live_test_max_n if live_test else (2 if dry_run else 50)
        ),
    }
    if contact_scope == "new":
        caps["reply_cap"] = 0
    elif contact_scope == "existing":
        caps["opener_target"] = 0
        caps["swipe_cap"] = 0
    stand_in = stand_in_package or "ai.mobilerun.mockdating"
    job = {
        "job_id": job_id,
        "kind": "dating",
        "status": "running",
        "device_id": device_id,
        "dry_run": dry_run,
        "live_test": live_test,
        "live_test_max_n": live_test_max_n,
        "contact_scope": contact_scope,
        "stand_in_package": stand_in,
        "created_at": int(datetime.now().timestamp()),
        "next_run_at": int(datetime.now().timestamp()),
        "speed_preset": dating_mode_state.get("speed_preset")
        or agent_mode_state.get("speed_preset", "balanced"),
        "caps": caps,
        "state": {
            "openers_sent": 0,
            "replies_sent": 0,
            "swipes_done": 0,
            "steps": 0,
            "steps_detail": [],
            "stand_in_package": stand_in,
            "current_app": stand_in,
            "contact_scope": contact_scope,
            "dry_run": dry_run,
            "live_test": live_test,
            "live_test_max_n": live_test_max_n,
            "live_likes_done": 0,
            "live_messages_done": 0,
        },
        "ttl": int(datetime.now().timestamp()) + 7 * 86400,
    }
    agent_mode_state["mode"] = "dating"
    try:
        from storage import get_job, put_job
    except ImportError:
        from backend.storage import get_job, put_job  # type: ignore
    try:
        put_job(job)
        persisted = get_job(job_id)
        if not persisted and os.environ.get("USE_AWS_STORAGE", "").lower() == "true":
            raise RuntimeError(f"dating job {job_id} not readable after put_job")
        _kick_job(job_id)
    except Exception as e:
        dating_mode_state["running"] = False
        dating_mode_state.pop("job_id", None)
        logger.exception("Could not persist dating job: %s", e)
        raise HTTPException(
            status_code=503, detail=f"Could not persist dating job: {e}"
        ) from e

    _save_dating_runtime(auth)
    return {
        "status": "started",
        "state": dating_mode_state,
        "job": job,
        "activity": _activity_for_mode("dating", job_id),
    }


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
            if job and job.get("dating_run"):
                # Stop the app that is on now; its queue dies with it
                try:
                    from dating_run import latest_in_run
                    from storage import list_recent_jobs
                except ImportError:
                    from backend.dating_run import latest_in_run  # type: ignore
                    from backend.storage import list_recent_jobs  # type: ignore

                job = latest_in_run(job_id, list_recent_jobs(limit=40)) or job
            if job:
                job["status"] = "stopped"
                put_job(job)
                # Restore overlay bubble — cancel skips _end_job_cleanup otherwise
                did = str(job.get("device_id") or "")
                if did:
                    try:
                        from cloud_agent import _end_job_cleanup
                        from device_rpc import call_device
                    except ImportError:
                        from backend.cloud_agent import (  # type: ignore
                            _end_job_cleanup,
                        )
                        from backend.device_rpc import call_device  # type: ignore

                    _end_job_cleanup(job, did, call_device)
        except Exception as e:
            logger.warning("Could not stop job: %s", e)

    # r45: also stop any other running dating job (stuck/queued ones kept the
    # phone locked so a new Badoo run could not start, 24 Nov).
    stopped_ids: List[str] = []
    try:
        try:
            from dating_run import running_dating_jobs
            from storage import list_recent_jobs, put_job
        except ImportError:
            from backend.dating_run import running_dating_jobs  # type: ignore
            from backend.storage import list_recent_jobs, put_job  # type: ignore
        for j in running_dating_jobs(list_recent_jobs(limit=50)):
            j["status"] = "stopped"
            j["error"] = j.get("error") or "Stopped from the portal"
            j["updated_at"] = int(time.time())
            put_job(j)
            stopped_ids.append(str(j.get("job_id") or ""))
            did = str(j.get("device_id") or "")
            if did:
                try:
                    try:
                        from cloud_agent import _end_job_cleanup
                        from device_rpc import call_device
                    except ImportError:
                        from backend.cloud_agent import _end_job_cleanup  # type: ignore
                        from backend.device_rpc import call_device  # type: ignore
                    _end_job_cleanup(j, did, call_device)
                except Exception:
                    pass
    except Exception as e:
        logger.warning("Could not sweep dating jobs: %s", e)

    _save_dating_runtime(auth)
    return {"status": "stopped", "state": dating_mode_state, "stopped": stopped_ids}


@app.post("/api/dating/pause")
async def pause_dating_mode(auth: Optional[dict] = Depends(optional_verify_token)):
    """Pause dating mode."""
    if not dating_mode_state["running"]:
        raise HTTPException(status_code=400, detail="Dating mode not running")

    dating_mode_state["paused"] = not dating_mode_state["paused"]
    _save_dating_runtime(auth)

    return {
        "status": "paused" if dating_mode_state["paused"] else "resumed",
        "state": dating_mode_state,
    }


@app.get("/api/dating/status")
async def get_dating_status(auth: Optional[dict] = Depends(optional_verify_token)):
    """Get dating mode status + live activity steps."""
    _load_dating_runtime(auth)
    activity = _activity_for_mode("dating", dating_mode_state.get("job_id"))
    return {
        **dating_mode_state,
        "activity": activity,
        "job_id": dating_mode_state.get("job_id") or activity.get("job_id"),
    }


@app.get("/api/dating/activity")
async def get_dating_activity(auth: Optional[dict] = Depends(optional_verify_token)):
    """Live step list for the current/recent dating job."""
    _load_dating_runtime(auth)
    return _activity_for_mode("dating", dating_mode_state.get("job_id"))


@app.post("/api/jobs/{job_id}/tick")
async def tick_job(job_id: str, auth: Optional[dict] = Depends(optional_verify_token)):
    """Advance one dating/social/agent step (used by live-activity E2E + dry-run)."""
    import traceback as _tb

    try:
        from storage import get_job, put_job
    except ImportError:
        from backend.storage import get_job, put_job  # type: ignore
    try:
        from step_worker import process_job
    except ImportError:
        from backend.step_worker import process_job  # type: ignore

    try:
        job = get_job(job_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"get_job failed: {e}") from e
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    if str(job.get("status") or "") not in ("running", "paused"):
        return {"status": job.get("status"), "job_id": job_id, "skipped": True}
    # Force due now
    job["next_run_at"] = int(time.time()) - 1
    job["status"] = "running"
    try:
        put_job(job)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"put_job failed: {e}") from e
    # Off-loop so device WS can deliver RPC replies during the step
    try:
        await asyncio.to_thread(process_job, job)
    except Exception as e:
        # Surface the real crash (previously a bare 500) so we can diagnose
        # prod step-worker failures without CloudWatch.
        updated = get_job(job_id) or job
        return {
            "status": updated.get("status") or "failed",
            "job_id": job_id,
            "error": f"process_job: {e}",
            "traceback": _tb.format_exc()[-4000:],
            "job_error": updated.get("error"),
            "result": updated.get("result"),
            "steps": int((updated.get("state") or {}).get("steps") or 0),
        }
    updated = get_job(job_id) or job
    kind = str(updated.get("kind") or "agent")
    try:
        activity = _activity_for_mode(kind, job_id)
    except Exception as e:
        activity = {"error": f"activity failed: {e}"}
    return {
        "status": updated.get("status"),
        "job_id": job_id,
        "activity": activity,
        "error": updated.get("error"),
        "result": updated.get("result"),
        "steps": int((updated.get("state") or {}).get("steps") or 0),
    }


@app.get("/api/dating/review-queue")
async def get_review_queue(auth: Optional[dict] = Depends(optional_verify_token)):
    """Review queue / Needs-you removed — always empty."""
    return {"messages": [], "needs_you": [], "removed": True}


@app.post("/api/dating/review/{message_id}/approve")
async def approve_message(
    message_id: str, auth: Optional[dict] = Depends(optional_verify_token)
):
    """Approve a message for sending."""
    dating_mode_state["review_queue"] = [
        msg for msg in dating_mode_state["review_queue"] if msg["id"] != message_id
    ]
    get_needs_you_queue(auth).approve(message_id)
    _save_dating_runtime(auth)
    return {"status": "approved", "message_id": message_id}


@app.post("/api/dating/review/{message_id}/reject")
async def reject_message(
    message_id: str, auth: Optional[dict] = Depends(optional_verify_token)
):
    """Reject a message."""
    dating_mode_state["review_queue"] = [
        msg for msg in dating_mode_state["review_queue"] if msg["id"] != message_id
    ]
    get_needs_you_queue(auth).reject(message_id)
    _save_dating_runtime(auth)
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
            get_needs_you_queue(auth).edit(message_id, message.message)
            _save_dating_runtime(auth)
            return {"status": "updated", "message": message.dict()}

    # May only exist in Needs-you (synced dating item)
    item = get_needs_you_queue(auth).edit(message_id, message.message)
    if item:
        return {"status": "updated", "message": item.to_dict()}

    raise HTTPException(status_code=404, detail="Message not found")


@app.post("/api/dating/review")
async def enqueue_dating_review(
    message: DatingMessage, auth: Optional[dict] = Depends(optional_verify_token)
):
    """Review / Needs-you queue removed — accept payload but do not store."""
    payload = message.dict() if hasattr(message, "dict") else message.model_dump()
    return {
        "status": "skipped",
        "message": payload,
        "needs_you_id": None,
        "badge": 0,
        "removed": True,
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
    _load_social_runtime(auth)
    activity = _activity_for_mode("social", social_mode_state.get("job_id"))
    return {
        **social_mode_state,
        "needs_you_badge": 0,
        "activity": activity,
        "job_id": social_mode_state.get("job_id") or activity.get("job_id"),
    }


@app.get("/api/social/activity")
async def get_social_activity(auth: Optional[dict] = Depends(optional_verify_token)):
    return _activity_for_mode("social", social_mode_state.get("job_id"))


class SocialRunBody(BaseModel):
    device_id: Optional[str] = None
    app: str
    action: str  # message | reply
    contact: Optional[str] = None
    message: Optional[str] = None
    dry_run: bool = True


@app.post("/api/social/run")
async def social_run(
    body: SocialRunBody, auth: Optional[dict] = Depends(optional_verify_token)
):
    """Social page: message this person / reply to messages. No swipes or likes."""
    try:
        from social_run import build_job as build_social_job
    except ImportError:
        from backend.social_run import build_job as build_social_job  # type: ignore
    try:
        from device_push import device_is_reachable
    except ImportError:
        try:
            from backend.device_push import device_is_reachable  # type: ignore
        except ImportError:
            device_is_reachable = lambda _d: False  # type: ignore
    try:
        from storage import put_job
    except ImportError:
        from backend.storage import put_job  # type: ignore

    try:
        job = build_social_job(
            device_id=str(body.device_id or "").strip(),
            pkg=str(body.app or "").strip().lower(),
            action=str(body.action or "").strip().lower(),
            contact=body.contact or "",
            message=body.message or "",
            dry_run=bool(body.dry_run),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    did = job["device_id"]
    if not did or did == "default":
        raise HTTPException(
            status_code=400, detail="Pick your phone in the device list first"
        )
    mem = connected_devices.get(did) or {}
    if not (mem.get("connected") or device_is_reachable(did)):
        raise HTTPException(
            status_code=400,
            detail="Phone offline — open MobileRun on the phone and wait "
            "until Devices shows Connected",
        )
    try:
        put_job(job)
        _kick_job(job["job_id"])
    except Exception as e:
        logger.exception("Could not start social run: %s", e)
        raise HTTPException(
            status_code=503, detail=f"Could not start: {e}"
        ) from e
    _load_social_runtime(auth)
    social_mode_state["running"] = True
    social_mode_state["paused"] = False
    social_mode_state["job_id"] = job["job_id"]
    _save_social_runtime(auth)  # Stop may land on another Lambda
    return {
        "status": "started",
        "state": social_mode_state,
        "job": job,
        "activity": _activity_for_mode("social", job["job_id"]),
    }


@app.post("/api/social/start")
async def start_social_mode(
    body: Optional[ModeStartBody] = None,
    auth: Optional[dict] = Depends(optional_verify_token),
    device_id: str = "default",
    dry_run: bool = True,
    stand_in_package: Optional[str] = None,
):
    """Start social mode as a step-driven job (defaults to dry_run)."""
    _load_social_runtime(auth)
    existing = social_mode_state.get("job_id")
    if social_mode_state.get("running") and _active_mode_job("social", existing):
        raise HTTPException(status_code=400, detail="Social mode already running")
    social_mode_state["running"] = False
    social_mode_state.pop("job_id", None)
    if body:
        device_id = body.device_id or device_id
        dry_run = body.dry_run if body.dry_run is not None else dry_run
        stand_in_package = body.stand_in_package or stand_in_package

    social_mode_state["running"] = True
    social_mode_state["paused"] = False
    agent_mode_state["mode"] = "social"

    job_id = f"social_{secrets.token_hex(8)}"
    social_mode_state["job_id"] = job_id
    stand_in = stand_in_package or "com.google.android.apps.messaging"
    max_steps = int(
        (body.max_steps if body and body.max_steps else None) or (6 if dry_run else 40)
    )
    job = {
        "job_id": job_id,
        "kind": "social",
        "status": "running",
        "device_id": device_id,
        "dry_run": dry_run,
        "stand_in_package": stand_in,
        "max_steps": max_steps,
        "created_at": int(datetime.now().timestamp()),
        "next_run_at": int(datetime.now().timestamp()),
        "speed_preset": social_mode_state.get("speed_preset")
        or agent_mode_state.get("speed_preset", "balanced"),
        "state": {
            "steps": 0,
            "steps_detail": [],
            "stand_in_package": stand_in,
            "current_app": stand_in,
            "drafts_prepared": 0,
        },
        "ttl": int(datetime.now().timestamp()) + 7 * 86400,
    }
    try:
        from storage import get_job, put_job
    except ImportError:
        from backend.storage import get_job, put_job  # type: ignore
    try:
        put_job(job)
        persisted = get_job(job_id)
        if not persisted and os.environ.get("USE_AWS_STORAGE", "").lower() == "true":
            raise RuntimeError(f"social job {job_id} not readable after put_job")
        _kick_job(job_id)
    except Exception as e:
        social_mode_state["running"] = False
        social_mode_state.pop("job_id", None)
        logger.exception("Could not persist social job: %s", e)
        raise HTTPException(
            status_code=503, detail=f"Could not persist social job: {e}"
        ) from e

    _save_social_runtime(auth)
    return {
        "status": "started",
        "state": social_mode_state,
        "job": job,
        "activity": _activity_for_mode("social", job_id),
    }


@app.post("/api/social/stop")
async def stop_social_mode(auth: Optional[dict] = Depends(optional_verify_token)):
    _load_social_runtime(auth)
    social_mode_state["running"] = False
    social_mode_state["paused"] = False
    job_id = social_mode_state.pop("job_id", None)
    if job_id:
        try:
            from storage import get_job, put_job

            job = get_job(job_id)
            if job:
                job["status"] = "stopped"
                put_job(job)
        except Exception as e:
            logger.warning("Could not stop social job: %s", e)
    _save_social_runtime(auth)
    return {"status": "stopped", "state": social_mode_state}


@app.post("/api/social/pause")
async def pause_social_mode(auth: Optional[dict] = Depends(optional_verify_token)):
    social_mode_state["paused"] = not social_mode_state.get("paused", False)
    job_id = social_mode_state.get("job_id")
    if job_id:
        try:
            from storage import get_job, put_job

            job = get_job(job_id)
            if job:
                job["status"] = "paused" if social_mode_state["paused"] else "running"
                put_job(job)
                if not social_mode_state["paused"]:
                    _kick_job(job_id)
        except Exception as e:
            logger.warning("Could not pause social job: %s", e)
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
    """Prepare outbound reply: signature applied; always auto-ok (no Needs-you)."""
    from mobilerun.social.agent import prepare_outbound

    cfg = _social_config()

    # Queue unused — prepare_outbound always returns needs_you=False
    class _NoQueue:
        def add(self, *a, **k):
            raise RuntimeError("needs-you queue removed")

        def get(self, *a, **k):
            return None

        def pending_count(self):
            return 0

    decision = prepare_outbound(
        draft_reply=body.draft_reply,
        config=cfg,
        queue=_NoQueue(),  # type: ignore[arg-type]
        app_name=body.app_name,
        package_name=body.package_name,
        conversation_id=body.conversation_id,
        contact_name=body.contact_name,
        inbound_preview=body.inbound_preview,
        confidence=body.confidence,
        is_new_contact=body.is_new_contact,
    )
    return {
        **decision.to_dict(),
        "badge": 0,
        "notify": {},
        "speed_preset": cfg.speed_preset,
    }


@app.get("/api/needs-you")
async def list_needs_you(
    source: Optional[str] = None,
    auth: Optional[dict] = Depends(optional_verify_token),
):
    """Needs-you portal removed — empty stub for old clients."""
    return {"badge": 0, "items": [], "all": [], "removed": True}


@app.post("/api/needs-you/{item_id}/approve")
@app.post("/api/needs-you/{item_id}/reject")
@app.post("/api/needs-you/{item_id}/edit")
async def needs_you_actions_removed(item_id: str):
    raise HTTPException(
        status_code=410, detail="Needs-you portal removed from MacMobileRun"
    )


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
                try:
                    from dating_stats_io import load_dating_stats
                except ImportError:
                    from backend.dating_stats_io import load_dating_stats  # type: ignore

                stats = load_dating_stats(_dating_user_id(auth)).get_summary()
                return {"message": "Dating stats", "stats": stats}
            except Exception as e:
                return {"message": f"Stats unavailable: {e}", "stats": {}}
        if intent == "needs_you_list":
            return {
                "message": "Needs-you portal removed — no review queue",
                "badge": 0,
                "items": [],
                "removed": True,
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
                # Auto-pick first live device for this owner when UI forgot device_id
                owner = _owner_key(auth)
                try:
                    from device_registry import merge_device_lists
                except ImportError:
                    from backend.device_registry import merge_device_lists  # type: ignore

                merged = merge_device_lists(connected_devices, owner)
                live = next(
                    (
                        d
                        for d in merged
                        if d.get("connected") and _device_visible_to(d, auth)
                    ),
                    None,
                )
                if live:
                    did = str(live["device_id"])
                else:
                    return {
                        "message": "No device selected and none online — open Devices, connect a phone, then pick it in Chat settings.",
                        "error": "no_device",
                    }
            mode = params.get("mode") or agent_mode_state.get("mode", "normal")
            speed = params.get("speed_preset") or agent_mode_state.get(
                "speed_preset", "balanced"
            )
            try:
                task = await submit_task(
                    TaskRequest(
                        device_id=did,
                        instruction=instruction,
                        mode=mode,
                        speed_preset=speed,
                    ),
                    auth=auth,
                )
            except HTTPException as he:
                detail = he.detail if isinstance(he.detail, str) else str(he.detail)
                return {
                    "message": detail,
                    "error": detail,
                    "device_id": did,
                    "instruction": instruction,
                }
            dumped = task.model_dump() if hasattr(task, "model_dump") else task.dict()
            status = dumped.get("status")
            err = dumped.get("error")
            if status == "failed" or err:
                return {
                    "message": err or f"Task failed on {did}",
                    "error": err or "task_failed",
                    "task": dumped,
                    "device_id": did,
                }
            return {
                "message": f"Started task {task.task_id}: {instruction}",
                "task": dumped,
                "task_id": task.task_id,
                "device_id": did,
                "steps": [
                    {
                        "title": "Dispatched to phone",
                        "subtext": f"{did} · {status}",
                        "done": True,
                    },
                    {
                        "title": "Waiting for device execution",
                        "subtext": instruction,
                        "done": False,
                    },
                ],
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
