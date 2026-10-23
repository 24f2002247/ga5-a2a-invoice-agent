from fastapi import Request, HTTPException, status
from app.config import settings


def verify_a2a_auth(request: Request) -> str:
    """
    Verifies Bearer token FIRST, then A2A-Version header.
    Returns the authenticated principal string.
    """
    # 1. Validate Authorization Bearer token FIRST (missing auth returns 401/403)
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

    # 2. Validate A2A-Version header SECOND (bad version returns 400)
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

    return token


def verify_a2a_content_type(request: Request):
    """
    Validates that request Content-Type is application/a2a+json for endpoints accepting a payload.
    Returns 415 Unsupported Media Type if invalid.
    """
    content_type = request.headers.get("Content-Type", "")
    main_type = content_type.split(";")[0].strip().lower()
    if main_type != "application/a2a+json":
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Invalid Content-Type header (expected 'application/a2a+json')"
        )
