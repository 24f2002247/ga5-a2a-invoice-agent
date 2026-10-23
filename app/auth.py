from fastapi import Request, HTTPException, status
from app.config import settings


def verify_a2a_auth(request: Request) -> str:
    """
    Verifies A2A-Version header and Bearer token.
    Returns the authenticated principal string.
    """
    # 1. Validate A2A-Version
    version = request.headers.get("A2A-Version")
    if not version:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing A2A-Version header (expected '1.0')"
        )
    version_clean = version.split(";")[0].strip()
    if version_clean != "1.0":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported A2A-Version header: '{version}' (expected '1.0')"
        )

    # 2. Validate Authorization Bearer token
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Bearer authentication header"
        )

    token = auth_header[7:].strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Empty Bearer token"
        )

    # If specific allowed tokens are configured, validate
    allowed = settings.allowed_tokens
    if allowed is not None and token not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid Bearer token credentials"
        )

    return token


def verify_a2a_content_type(request: Request):
    """
    Validates that request Content-Type is application/a2a+json for endpoints accepting a payload.
    """
    content_type = request.headers.get("Content-Type", "")
    # Allow parameters like charset=utf-8
    main_type = content_type.split(";")[0].strip().lower()
    if main_type != "application/a2a+json":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Content-Type header (expected 'application/a2a+json')"
        )
