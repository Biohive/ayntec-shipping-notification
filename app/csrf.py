"""CSRF protection: per-session token generation and FastAPI dependency for validation."""

import logging
import secrets

from fastapi import Form, HTTPException, Request

logger = logging.getLogger(__name__)

_CSRF_SESSION_KEY = "_csrf_token"


def get_csrf_token(request: Request) -> str:
    """Return the CSRF token stored in *request*'s session.

    A new token is generated and stored when none exists yet.  This function
    is also registered as a Jinja2 global so templates can call it directly::

        {{ csrf_token(request) }}
    """
    token = request.session.get(_CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_hex(32)
        request.session[_CSRF_SESSION_KEY] = token
    return token


def verify_csrf(request: Request, csrf_token: str = Form("")) -> None:
    """FastAPI dependency: validate the CSRF token submitted with a form POST.

    Raises HTTP 403 if the token is absent or does not match the session token.
    Use as a dependency on every state-changing POST handler::

        @router.post("/some-action")
        async def some_action(_csrf: None = Depends(verify_csrf), ...):
            ...
    """
    session_token = request.session.get(_CSRF_SESSION_KEY)
    if not csrf_token or not session_token or not secrets.compare_digest(csrf_token, session_token):
        logger.warning(
            "CSRF validation failed for %s %s (client=%s)",
            request.method,
            request.url.path,
            request.client.host if request.client else "unknown",
        )
        raise HTTPException(status_code=403, detail="CSRF validation failed.")
