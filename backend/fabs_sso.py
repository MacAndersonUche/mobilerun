"""Fabs SSO token minting for single sign-on to Auto-Fab."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time


def _base64url_encode(data: bytes) -> str:
    """Encode bytes as base64url (no padding)."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def mint_fabs_sso_token(username: str, secret: str) -> str:
    """
    Mint a Fabs SSO token for the given username.

    Token format: <payload_b64>.<signature_b64>
    Payload: {"sub": username, "iat": unix_timestamp, "exp": unix_timestamp + 60, "nonce": hex}
    Signature: HMAC-SHA256(payload_b64, secret)

    Args:
        username: The username to authenticate as (e.g., "Mac")
        secret: The shared secret for HMAC signing

    Returns:
        SSO token string

    Raises:
        ValueError: If secret is empty or username is empty
    """
    if not secret:
        raise ValueError("FABS_SSO_SECRET is required")
    if not username:
        raise ValueError("Username is required")

    now = int(time.time())
    payload = {
        "sub": username,
        "iat": now,
        "exp": now + 60,
        "nonce": secrets.token_hex(16),
    }

    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    payload_b64 = _base64url_encode(payload_json.encode("utf-8"))

    signature = hmac.new(
        secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256
    ).digest()
    signature_b64 = _base64url_encode(signature)

    return f"{payload_b64}.{signature_b64}"


def get_fabs_sso_secret() -> str:
    """Get the FABS_SSO_SECRET from environment."""
    return os.environ.get("FABS_SSO_SECRET", "")


def create_fabs_sso_link(username: str = "Mac") -> str:
    """
    Create a Fabs SSO link for the given username.

    Args:
        username: The username to authenticate as (defaults to "Mac")

    Returns:
        Full SSO URL with token in fragment

    Raises:
        ValueError: If FABS_SSO_SECRET is not configured
    """
    secret = get_fabs_sso_secret()
    if not secret:
        raise ValueError("FABS_SSO_SECRET environment variable is not configured")

    token = mint_fabs_sso_token(username, secret)
    return f"https://fabswingerauto.netlify.app/sso#token={token}"
