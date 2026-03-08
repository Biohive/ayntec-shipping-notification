"""OIDC authentication helpers using Authlib."""

import logging
from authlib.integrations.starlette_client import OAuth
from starlette.requests import Request
from app.config import settings

logger = logging.getLogger(__name__)

oauth = OAuth()

# Only register if OIDC is configured
if settings.oidc_client_id and settings.oidc_discovery_url:
    oauth.register(
        name="authentik",
        client_id=settings.oidc_client_id,
        client_secret=settings.oidc_client_secret,
        server_metadata_url=settings.oidc_discovery_url,
        client_kwargs={
            "scope": "openid email profile",
        },
    )
else:
    logger.warning(
        "OIDC not configured – set OIDC_CLIENT_ID, OIDC_CLIENT_SECRET, and "
        "OIDC_DISCOVERY_URL in your .env file."
    )


def get_current_user(request: Request) -> dict | None:
    """Return the user info dict stored in the session, or None if not logged in."""
    return request.session.get("user")


def require_user(request: Request) -> dict:
    """Return user or raise redirect (caller must handle None return)."""
    return get_current_user(request)
