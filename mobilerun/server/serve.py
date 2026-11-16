"""Serve command - start local backend with UI."""

import asyncio
import logging
import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import Optional

import click
import qrcode

logger = logging.getLogger("mobilerun.serve")


def generate_pairing_qr(backend_url: str, token: str) -> str:
    """Generate ASCII QR code for device pairing."""
    pairing_data = f"{backend_url}|{token}"
    qr = qrcode.QRCode(border=2)
    qr.add_data(pairing_data)
    qr.make(fit=True)

    # Get ASCII representation
    matrix = qr.get_matrix()
    lines = []
    for row in matrix:
        line = "".join("██" if cell else "  " for cell in row)
        lines.append(line)

    return "\n".join(lines)


def find_frontend_dist() -> Optional[Path]:
    """Find the built frontend dist directory."""
    # Try several locations
    candidates = [
        Path(__file__).parent.parent.parent / "frontend" / "dist",
        Path.cwd() / "frontend" / "dist",
        Path.home() / ".mobilerun" / "frontend" / "dist",
    ]

    for path in candidates:
        if path.exists() and (path / "index.html").exists():
            return path

    return None


def check_frontend_build() -> bool:
    """Check if frontend is built, offer to build if not."""
    dist_path = find_frontend_dist()

    if dist_path:
        return True

    # Check if we can build it
    frontend_dir = Path(__file__).parent.parent.parent / "frontend"
    if not frontend_dir.exists():
        return False

    click.echo("Frontend not built. Building now...")
    try:
        subprocess.run(
            ["npm", "ci"],
            cwd=frontend_dir,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["npm", "run", "build"],
            cwd=frontend_dir,
            check=True,
            capture_output=True,
        )
        click.echo("✓ Frontend built successfully")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        logger.warning(f"Failed to build frontend: {e}")
        return False


@click.command(name="serve")
@click.option("--host", default="0.0.0.0", help="Host to bind to")
@click.option("--port", default=8000, help="Port to bind to")
@click.option("--no-browser", is_flag=True, help="Don't auto-open browser")
@click.option(
    "--allow-unauthenticated", is_flag=True, help="Disable JWT auth (local use only)"
)
def serve_command(host: str, port: int, no_browser: bool, allow_unauthenticated: bool):
    """
    Start the Mobilerun control center.

    This starts the backend server and serves the web UI.
    Open the displayed URL in your browser and scan the QR code with your phone.
    """
    import uvicorn

    # Set environment variables for the backend
    os.environ["HOST"] = host
    os.environ["PORT"] = str(port)

    if allow_unauthenticated:
        os.environ["ALLOW_UNAUTHENTICATED"] = "true"

    # Generate pairing token
    import secrets

    pairing_token = secrets.token_urlsafe(32)
    os.environ["PAIRING_TOKEN"] = pairing_token

    # Check frontend build
    frontend_ready = check_frontend_build()
    dist_path = find_frontend_dist()

    if frontend_ready and dist_path:
        os.environ["FRONTEND_DIR"] = str(dist_path)

    # Display startup information
    backend_url = (
        f"http://localhost:{port}" if host == "0.0.0.0" else f"http://{host}:{port}"
    )
    ui_url = f"{backend_url}/"

    click.echo("\n" + "=" * 70)
    click.echo("🚀 Mobilerun Control Center Starting...")
    click.echo("=" * 70)
    click.echo(f"\n📱 Backend API: {backend_url}")
    click.echo(f"🌐 Web UI: {ui_url}")

    if frontend_ready:
        click.echo(f"✓ Frontend served from: {dist_path}")
    else:
        click.echo("⚠️  Frontend not available (serve from Netlify or build manually)")

    click.echo("\n" + "─" * 70)
    click.echo("📲 PAIR YOUR ANDROID DEVICE:")
    click.echo("─" * 70)
    click.echo("\n1. Install the Mobilerun app on your phone")
    click.echo("2. Enable Accessibility Service in Settings")
    click.echo("3. Return to app and scan this QR code:\n")

    # Print QR code
    try:
        qr_code = generate_pairing_qr(backend_url, pairing_token)
        click.echo(qr_code)
    except Exception as e:
        logger.warning(f"Failed to generate QR code: {e}")
        click.echo(f"\nPairing URL: {backend_url}")
        click.echo(f"Pairing Token: {pairing_token}")

    click.echo("\n" + "─" * 70)
    click.echo("💡 Quick Start:")
    click.echo("─" * 70)
    click.echo(f"  • Open {ui_url} in your browser")
    click.echo("  • Pair your phone using the QR code above")
    click.echo("  • Type tasks in the UI (e.g., 'open WhatsApp')")
    click.echo("  • Or use CLI: mobilerun run 'your task here'")
    click.echo("\n" + "=" * 70 + "\n")

    # Auto-open browser
    if not no_browser and frontend_ready:
        time.sleep(1)  # Give server a moment to start
        try:
            webbrowser.open(ui_url)
            click.echo(f"✓ Opened {ui_url} in your browser\n")
        except Exception as e:
            logger.warning(f"Failed to open browser: {e}")

    # Advertise on LAN so phones discover via NSD/mDNS (_mobilerun._tcp)
    advertiser = None
    try:
        from mobilerun.server.mdns import MobilerunAdvertiser

        advertiser = MobilerunAdvertiser(port=port, host=host)
        if advertiser.start():
            click.echo(
                f"📡 mDNS: _mobilerun._tcp → {advertiser.lan_http} "
                f"(phones prefer this over cloud when on same Wi‑Fi)"
            )
            os.environ.setdefault("LAN_HTTP_URL", advertiser.lan_http)
            os.environ.setdefault("LAN_WS_URL", advertiser.lan_ws)
        else:
            click.echo(
                "⚠️  mDNS advertise unavailable (install zeroconf). "
                "QR still includes LAN IP for direct connect."
            )
    except Exception as e:
        logger.warning("mDNS setup failed: %s", e)

    # Import here to ensure env vars are set first
    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "backend"))
    from backend.main import app

    # Start the server
    try:
        uvicorn.run(
            app,
            host=host,
            port=port,
            log_level="info",
            access_log=True,
        )
    except KeyboardInterrupt:
        click.echo("\n\n👋 Shutting down Mobilerun Control Center...")
    finally:
        if advertiser:
            advertiser.stop()
