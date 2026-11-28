"""Unit tests for Fabs SSO token minting."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from unittest.mock import patch

import pytest

from backend.fabs_sso import (
    _base64url_encode,
    create_fabs_sso_link,
    get_fabs_sso_secret,
    mint_fabs_sso_token,
)


def test_base64url_encode():
    """Test base64url encoding strips padding."""
    assert _base64url_encode(b"hello") == "aGVsbG8"
    assert _base64url_encode(b"test") == "dGVzdA"
    assert "=" not in _base64url_encode(b"padding test here")


def test_mint_token_format():
    """Test token has correct format: payload.signature."""
    token = mint_fabs_sso_token("Mac", "test-secret")
    parts = token.split(".")
    assert len(parts) == 2, "Token must have exactly 2 parts separated by dot"

    payload_b64, signature_b64 = parts
    assert len(payload_b64) > 0, "Payload must not be empty"
    assert len(signature_b64) > 0, "Signature must not be empty"

    # Verify base64url (no padding, URL-safe)
    for char in payload_b64 + signature_b64:
        assert (
            char in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
        )


def test_mint_token_payload_structure():
    """Test token payload has required fields."""
    token = mint_fabs_sso_token("Mac", "test-secret")
    payload_b64 = token.split(".")[0]

    # Decode base64url
    padding = "=" * (4 - len(payload_b64) % 4)
    payload_json = base64.urlsafe_b64decode(payload_b64 + padding)
    payload = json.loads(payload_json)

    assert payload["sub"] == "Mac"
    assert "iat" in payload
    assert "exp" in payload
    assert "nonce" in payload

    # Check timestamp values
    now = int(time.time())
    assert abs(payload["iat"] - now) < 2, "iat should be current timestamp"
    assert payload["exp"] == payload["iat"] + 60, "exp should be iat + 60 seconds"

    # Check nonce is hex string
    assert len(payload["nonce"]) == 32, "nonce should be 16 bytes (32 hex chars)"
    assert all(c in "0123456789abcdef" for c in payload["nonce"])


def test_mint_token_expiry():
    """Test token expiry is exactly 60 seconds from issuance."""
    token = mint_fabs_sso_token("TestUser", "secret123")
    payload_b64 = token.split(".")[0]

    padding = "=" * (4 - len(payload_b64) % 4)
    payload = json.loads(base64.urlsafe_b64decode(payload_b64 + padding))

    assert payload["exp"] - payload["iat"] == 60


def test_mint_token_hmac_signature():
    """Test HMAC-SHA256 signature is computed correctly."""
    secret = "test-secret-key"
    token = mint_fabs_sso_token("Mac", secret)
    payload_b64, signature_b64 = token.split(".")

    # Recompute signature
    expected_sig = hmac.new(
        secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256
    ).digest()
    expected_sig_b64 = (
        base64.urlsafe_b64encode(expected_sig).rstrip(b"=").decode("ascii")
    )

    assert signature_b64 == expected_sig_b64, "Signature must match HMAC-SHA256"


def test_mint_token_different_secrets_different_signatures():
    """Test different secrets produce different signatures."""
    token1 = mint_fabs_sso_token("Mac", "secret1")
    token2 = mint_fabs_sso_token("Mac", "secret2")

    sig1 = token1.split(".")[1]
    sig2 = token2.split(".")[1]

    assert sig1 != sig2, "Different secrets must produce different signatures"


def test_mint_token_nonce_uniqueness():
    """Test each token gets a unique nonce."""
    tokens = [mint_fabs_sso_token("Mac", "test") for _ in range(10)]

    nonces = []
    for token in tokens:
        payload_b64 = token.split(".")[0]
        padding = "=" * (4 - len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64 + padding))
        nonces.append(payload["nonce"])

    assert len(set(nonces)) == 10, "All nonces must be unique"


def test_mint_token_empty_secret_raises():
    """Test minting with empty secret raises ValueError."""
    with pytest.raises(ValueError, match="FABS_SSO_SECRET is required"):
        mint_fabs_sso_token("Mac", "")


def test_mint_token_empty_username_raises():
    """Test minting with empty username raises ValueError."""
    with pytest.raises(ValueError, match="Username is required"):
        mint_fabs_sso_token("", "secret")


def test_get_fabs_sso_secret_from_env():
    """Test secret retrieval from environment."""
    with patch.dict("os.environ", {"FABS_SSO_SECRET": "my-secret"}):
        assert get_fabs_sso_secret() == "my-secret"


def test_get_fabs_sso_secret_missing():
    """Test secret retrieval when not set returns empty string."""
    with patch.dict("os.environ", {}, clear=True):
        assert get_fabs_sso_secret() == ""


def test_create_fabs_sso_link_format():
    """Test SSO link has correct format."""
    with patch.dict("os.environ", {"FABS_SSO_SECRET": "test-secret"}):
        link = create_fabs_sso_link()

        assert link.startswith("https://fabswingerauto.netlify.app/sso#token=")

        # Extract token from fragment
        fragment = link.split("#")[1]
        assert fragment.startswith("token=")
        token = fragment.split("token=")[1]
        assert "." in token
        assert len(token.split(".")) == 2


def test_create_fabs_sso_link_custom_username():
    """Test SSO link with custom username."""
    with patch.dict("os.environ", {"FABS_SSO_SECRET": "test-secret"}):
        link = create_fabs_sso_link("CustomUser")
        fragment = link.split("#")[1]
        token = fragment.split("token=")[1]
        payload_b64 = token.split(".")[0]

        padding = "=" * (4 - len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64 + padding))

        assert payload["sub"] == "CustomUser"


def test_create_fabs_sso_link_no_secret_raises():
    """Test link creation without secret raises ValueError."""
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(
            ValueError, match="FABS_SSO_SECRET environment variable is not configured"
        ):
            create_fabs_sso_link()


def test_token_url_safe():
    """Test token contains only URL-safe characters."""
    with patch.dict("os.environ", {"FABS_SSO_SECRET": "test-secret"}):
        link = create_fabs_sso_link()
        fragment = link.split("#")[1]
        token = fragment.split("token=")[1]

        # Token value should not contain +, or / (= is allowed in the fragment key)
        assert "+" not in token
        assert "/" not in token


def test_token_roundtrip_verification():
    """Test a token can be verified by the receiver."""
    secret = "shared-secret-between-portal-and-fabs"
    token = mint_fabs_sso_token("Mac", secret)
    payload_b64, signature_b64 = token.split(".")

    # Verify signature (as Auto-Fab would)
    expected_sig = hmac.new(
        secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256
    ).digest()
    expected_sig_b64 = (
        base64.urlsafe_b64encode(expected_sig).rstrip(b"=").decode("ascii")
    )

    assert signature_b64 == expected_sig_b64, "Signature verification must pass"

    # Decode payload
    padding = "=" * (4 - len(payload_b64) % 4)
    payload = json.loads(base64.urlsafe_b64decode(payload_b64 + padding))

    assert payload["sub"] == "Mac"
    assert payload["exp"] > int(time.time()), "Token should not be expired immediately"
