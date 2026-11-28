"""Fabs SSO token minting and verification for single sign-on to Auto-Fab."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Optional


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


_secret_cache: Optional[str] = None


def get_fabs_sso_secret() -> str:
    """
    Get the FABS_SSO_SECRET from AWS Secrets Manager (cached).

    Reads from the secret ARN specified in FABS_SSO_SECRET_ARN environment variable.
    The secret is cached in memory for the lifetime of the Lambda container.

    Returns:
        The secret value as a string.

    Raises:
        ValueError: If secret ARN is not configured or secret cannot be retrieved.
    """
    global _secret_cache

    if _secret_cache is not None:
        return _secret_cache

    secret_arn = os.environ.get("FABS_SSO_SECRET_ARN", "")
    if not secret_arn:
        raise ValueError("FABS_SSO_SECRET_ARN environment variable is not configured")

    try:
        import boto3

        client = boto3.client("secretsmanager")
        response = client.get_secret_value(SecretId=secret_arn)
        secret_data = json.loads(response["SecretString"])
        _secret_cache = secret_data.get("secret", "")

        if not _secret_cache:
            raise ValueError("Secret value is empty")

        return _secret_cache
    except Exception as e:
        raise ValueError(f"Failed to retrieve FABS_SSO_SECRET: {e}") from e


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


def verify_fabs_sso_token(token: str, secret: str) -> dict:
    """
    Verify a Fabs SSO token and extract claims.

    Args:
        token: The SSO token to verify (format: payload_b64.signature_b64)
        secret: The shared secret for HMAC verification

    Returns:
        Dict with verified payload: {"sub": "Mac", "iat": int, "exp": int, "nonce": str}

    Raises:
        ValueError: If token format is invalid, signature fails, or token is expired
    """
    if not token or not secret:
        raise ValueError("Token and secret are required")

    parts = token.split(".")
    if len(parts) != 2:
        raise ValueError("Invalid token format")

    payload_b64, signature_b64 = parts

    # Verify HMAC signature
    expected_sig = hmac.new(
        secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256
    ).digest()
    expected_sig_b64 = _base64url_encode(expected_sig)

    if signature_b64 != expected_sig_b64:
        raise ValueError("Invalid token signature")

    # Decode payload
    try:
        padding = "=" * (4 - len(payload_b64) % 4)
        payload_json = base64.urlsafe_b64decode(payload_b64 + padding)
        payload = json.loads(payload_json)
    except Exception as e:
        raise ValueError(f"Failed to decode token payload: {e}") from e

    # Verify expiry
    now = int(time.time())
    exp = payload.get("exp")
    if not exp or exp < now:
        raise ValueError("Token has expired")

    # Verify required fields
    if "sub" not in payload or "iat" not in payload or "nonce" not in payload:
        raise ValueError("Token missing required fields")

    return payload


def mark_nonce_used(nonce: str) -> None:
    """
    Mark a nonce as used in DynamoDB with TTL.

    Args:
        nonce: The nonce to mark as used

    Raises:
        ImportError: If boto3 is not available
        Exception: If DynamoDB operation fails
    """
    import boto3

    table_name = os.environ.get("SSO_NONCES_TABLE", "")
    if not table_name:
        raise ValueError("SSO_NONCES_TABLE environment variable not configured")

    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(table_name)

    # TTL 2 minutes (tokens expire in 60s, give some buffer)
    ttl = int(time.time()) + 120

    table.put_item(Item={"nonce": nonce, "ttl": ttl, "used_at": int(time.time())})


def is_nonce_used(nonce: str) -> bool:
    """
    Check if a nonce has already been used.

    Args:
        nonce: The nonce to check

    Returns:
        True if nonce was already used, False otherwise

    Raises:
        ImportError: If boto3 is not available
        Exception: If DynamoDB operation fails
    """
    import boto3

    table_name = os.environ.get("SSO_NONCES_TABLE", "")
    if not table_name:
        raise ValueError("SSO_NONCES_TABLE environment variable not configured")

    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(table_name)

    response = table.get_item(Key={"nonce": nonce})
    return "Item" in response
