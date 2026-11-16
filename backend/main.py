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
from pydantic import BaseModel

# Add mobilerun to path for local runs
if Path(__file__).parent.parent.name == "mobilerun":
    sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.auth import create_access_token, optional_verify_token

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

# In-memory state (for Lambda, consider DynamoDB)
connected_devices: Dict[str, Dict[str, Any]] = {}
active_runs: Dict[str, Dict[str, Any]] = {}
run_history: List[Dict[str, Any]] = []
websocket_clients: List[WebSocket] = []
pairing_tokens: Dict[str, Dict[str, Any]] = {}
device_websockets: Dict[str, WebSocket] = {}


# === Models ===

class DeviceInfo(BaseModel):
    device_id: str
    name: str
    platform: str
    connected: bool
    connection_type: str
    last_seen: datetime


class PairingRequest(BaseModel):
    device_name: str
    platform: str = "android"


class TaskRequest(BaseModel):
    device_id: str
    instruction: str
    max_steps: int = 15
    reasoning: bool = False
    vision: bool = False


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
    """Simple login endpoint (for development)."""
    # In production, verify against a user database
    if request.username == "admin" and request.password == os.environ.get("ADMIN_PASSWORD", "admin"):
        token = create_access_token({"sub": request.username})
        return {"access_token": token, "token_type": "bearer"}

    raise HTTPException(status_code=401, detail="Invalid credentials")


# === Main Endpoints ===

@app.get("/")
async def root():
    """Health check endpoint."""
    return {
        "service": "Mobilerun Backend",
        "version": "1.0.0",
        "status": "running",
        "devices_connected": len([d for d in connected_devices.values() if d.get("connected", False)]),
        "active_runs": len(active_runs),
    }


@app.get("/api/devices", response_model=List[DeviceInfo])
async def list_devices(auth: Optional[dict] = Depends(optional_verify_token)):
    """List all connected devices."""
    devices = []
    for device_id, device_data in connected_devices.items():
        devices.append(
            DeviceInfo(
                device_id=device_id,
                name=device_data["name"],
                platform=device_data["platform"],
                connected=device_data.get("connected", False),
                connection_type=device_data.get("connection_type", "unknown"),
                last_seen=device_data.get("last_seen", datetime.now()),
            )
        )
    return devices


@app.post("/api/devices/pair")
async def initiate_pairing(
    request: PairingRequest,
    auth: Optional[dict] = Depends(optional_verify_token)
):
    """
    Initiate device pairing. Returns QR code with backend URL and token.
    """
    token = secrets.token_urlsafe(32)

    # Get backend URL from environment or construct from request
    backend_url = os.environ.get("BACKEND_URL", "http://localhost:8000")

    pairing_data = {
        "token": token,
        "device_name": request.device_name,
        "platform": request.platform,
        "created_at": datetime.now(),
        "expires_at": datetime.now().timestamp() + 600,  # 10 minutes
        "backend_url": backend_url,
    }

    pairing_tokens[token] = pairing_data

    # Generate pairing URL with backend URL
    pairing_url = f"mobilerun://pair?token={token}&backend={backend_url}"

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
        "expires_in": 600,
    }


@app.websocket("/api/devices/connect")
async def device_websocket(websocket: WebSocket):
    """
    WebSocket for device connection (outbound from phone to backend).
    Device sends pairing token to authenticate.
    """
    await websocket.accept()
    device_id = None

    try:
        # Receive pairing/auth message
        data = await websocket.receive_json()
        token = data.get("token")

        if not token or token not in pairing_tokens:
            await websocket.send_json({"error": "Invalid or expired token"})
            await websocket.close()
            return

        pairing_data = pairing_tokens[token]
        device_id = data.get("device_id") or f"device_{secrets.token_hex(8)}"

        # Register device
        connected_devices[device_id] = {
            "device_id": device_id,
            "name": pairing_data["device_name"],
            "platform": pairing_data["platform"],
            "connected": True,
            "connection_type": "wifi",
            "last_seen": datetime.now(),
        }

        device_websockets[device_id] = websocket

        await websocket.send_json({
            "status": "connected",
            "device_id": device_id,
        })

        logger.info(f"Device {device_id} connected")

        # Keep connection alive and handle messages
        while True:
            try:
                message = await websocket.receive_json()
                await handle_device_message(device_id, message)
            except WebSocketDisconnect:
                break

    except Exception as e:
        logger.error(f"Device connection error: {e}")
    finally:
        # Clean up
        if device_id:
            if device_id in connected_devices:
                connected_devices[device_id]["connected"] = False
            if device_id in device_websockets:
                del device_websockets[device_id]
            logger.info(f"Device {device_id} disconnected")


async def handle_device_message(device_id: str, message: dict):
    """Handle messages from connected device."""
    msg_type = message.get("type")

    if msg_type == "heartbeat":
        connected_devices[device_id]["last_seen"] = datetime.now()
        ws = device_websockets.get(device_id)
        if ws:
            await ws.send_json({"type": "heartbeat_ack"})

    elif msg_type == "task_update":
        # Update task status
        task_id = message.get("task_id")
        if task_id in active_runs:
            active_runs[task_id].update(message.get("update", {}))

    elif msg_type == "screenshot":
        # Handle screenshot data
        pass


@app.post("/api/tasks", response_model=TaskStatus)
async def submit_task(
    request: TaskRequest,
    auth: Optional[dict] = Depends(optional_verify_token)
):
    """Submit a new automation task to a device."""
    if request.device_id not in connected_devices:
        raise HTTPException(status_code=404, detail="Device not found")

    if not connected_devices[request.device_id].get("connected", False):
        raise HTTPException(status_code=400, detail="Device not connected")

    task_id = f"task_{secrets.token_hex(8)}"

    task = {
        "task_id": task_id,
        "device_id": request.device_id,
        "instruction": request.instruction,
        "status": "pending",
        "current_step": 0,
        "max_steps": request.max_steps,
        "reasoning": request.reasoning,
        "vision": request.vision,
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
            await ws.send_json({
                "type": "run_task",
                "task_id": task_id,
                "instruction": request.instruction,
                "max_steps": request.max_steps,
                "reasoning": request.reasoning,
                "vision": request.vision,
            })
            task["status"] = "running"
        except Exception as e:
            logger.error(f"Failed to send task to device: {e}")
            task["status"] = "failed"
            task["error"] = "Failed to communicate with device"

    return TaskStatus(**task)


@app.get("/api/tasks/{task_id}", response_model=TaskStatus)
async def get_task_status(
    task_id: str,
    auth: Optional[dict] = Depends(optional_verify_token)
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
    limit: int = 50,
    auth: Optional[dict] = Depends(optional_verify_token)
):
    """List recent tasks."""
    tasks = list(active_runs.values()) + run_history
    tasks.sort(key=lambda t: t["started_at"], reverse=True)
    return [TaskStatus(**t) for t in tasks[:limit]]


@app.get("/api/config/llm")
async def get_llm_config(auth: Optional[dict] = Depends(optional_verify_token)):
    """Get current LLM configuration."""
    # Return config from environment
    return {
        "provider": os.environ.get("LLM_PROVIDER", "gemini"),
        "model": os.environ.get("LLM_MODEL", "gemini-3.8-flash"),
        "temperature": float(os.environ.get("LLM_TEMPERATURE", "0.7")),
        "max_tokens": int(os.environ.get("LLM_MAX_TOKENS", "2048")),
    }


@app.post("/api/config/llm")
async def update_llm_config(
    config: LLMConfig,
    auth: Optional[dict] = Depends(optional_verify_token)
):
    """Update LLM configuration."""
    # Validate provider
    supported = ["gemini", "openai", "anthropic"]
    if config.provider not in supported:
        raise HTTPException(
            status_code=400,
            detail=f"Provider must be one of: {', '.join(supported)}",
        )

    # Save to environment (Lambda environment variables managed via CDK)
    os.environ["LLM_PROVIDER"] = config.provider
    os.environ["LLM_MODEL"] = config.model
    os.environ["LLM_TEMPERATURE"] = str(config.temperature)
    os.environ["LLM_MAX_TOKENS"] = str(config.max_tokens)

    # Save API key
    env_key_map = {
        "gemini": "GOOGLE_API_KEY",
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
    }
    if config.api_key:
        os.environ[env_key_map[config.provider]] = config.api_key

    return {"status": "success"}


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
