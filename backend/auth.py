"""JWT authentication: local HS256 + optional AWS Cognito (RS256 JWKS)."""

from __future__ import annotations

import json
import os
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwk, jwt

# Local JWT configuration
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_MINUTES = 60 * 24 * 7  # 1 week

# Cognito (optional)
COGNITO_REGION = os.environ.get("COGNITO_REGION") or os.environ.get(
    "AWS_REGION", "eu-west-2"
)
COGNITO_USER_POOL_ID = os.environ.get("COGNITO_USER_POOL_ID", "")
COGNITO_APP_CLIENT_ID = os.environ.get("COGNITO_APP_CLIENT_ID", "")
# Comma-separated emails allowed to control devices (Mac's account)
ALLOWED_USER_EMAILS = {
    e.strip().lower()
    for e in os.environ.get(
        "ALLOWED_USER_EMAILS", "macandersonuche@yahoo.com,admin,ci-e2e"
    ).split(",")
    if e.strip()
}

security = HTTPBearer()

_jwks_cache: Dict[str, Any] = {"keys": None, "fetched_at": 0.0}


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Create a local HS256 JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRATION_MINUTES)

    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)


def cognito_enabled() -> bool:
    return bool(COGNITO_USER_POOL_ID)


def _cognito_issuer() -> str:
    return f"https://cognito-idp.{COGNITO_REGION}.amazonaws.com/{COGNITO_USER_POOL_ID}"


def _get_jwks() -> dict:
    now = time.time()
    if _jwks_cache["keys"] and now - float(_jwks_cache["fetched_at"]) < 3600:
        return _jwks_cache["keys"]
    url = f"{_cognito_issuer()}/.well-known/jwks.json"
    with urllib.request.urlopen(url, timeout=8) as resp:
        data = json.loads(resp.read().decode())
    _jwks_cache["keys"] = data
    _jwks_cache["fetched_at"] = now
    return data


def _decode_cognito(token: str) -> dict:
    headers = jwt.get_unverified_header(token)
    kid = headers.get("kid")
    jwks = _get_jwks()
    key_data = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
    if not key_data:
        raise JWTError("Unknown Cognito kid")
    key = jwk.construct(key_data)
    payload = jwt.decode(
        token,
        key,
        algorithms=["RS256"],
        audience=COGNITO_APP_CLIENT_ID or None,
        issuer=_cognito_issuer(),
        options={"verify_aud": bool(COGNITO_APP_CLIENT_ID)},
    )
    return payload


def _normalize(payload: dict) -> dict:
    email = (
        payload.get("email")
        or payload.get("cognito:username")
        or payload.get("username")
        or payload.get("sub")
    )
    normalized = {
        **payload,
        "sub": payload.get("sub"),
        "email": (str(email) if email else "").lower(),
        "user_id": payload.get("sub") or email,
    }
    if ALLOWED_USER_EMAILS and normalized["email"]:
        local = normalized["email"].split("@")[0]
        if (
            normalized["email"] not in ALLOWED_USER_EMAILS
            and local not in ALLOWED_USER_EMAILS
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account not authorized for this MobileRun instance",
            )
    return normalized


def decode_bearer(token: str) -> dict:
    """Decode local or Cognito JWT into a normalized claims dict."""
    try:
        header = jwt.get_unverified_header(token)
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e

    if COGNITO_USER_POOL_ID and header.get("alg") == "RS256":
        try:
            payload = _decode_cognito(token)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Cognito validation failed: {e}",
                headers={"WWW-Authenticate": "Bearer"},
            ) from e
    else:
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        except JWTError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
                headers={"WWW-Authenticate": "Bearer"},
            ) from e

    return _normalize(payload)


def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """Verify JWT token from Authorization header."""
    return decode_bearer(credentials.credentials)


def optional_verify_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(
        HTTPBearer(auto_error=False)
    ),
) -> Optional[dict]:
    """Verify token if provided; allow unauthenticated only when ALLOW_UNAUTHENTICATED."""
    if credentials is None:
        if os.environ.get("ALLOW_UNAUTHENTICATED", "false").lower() == "true":
            return None
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return decode_bearer(credentials.credentials)
