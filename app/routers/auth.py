"""Authentication routes: login, callback, logout."""

import logging
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from app.auth import oauth, get_current_user
from app.database import SessionLocal
from app.models import User, NotificationSetting
from app.config import settings
from app.templates import templates

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/login")
async def login(request: Request):
    """Redirect to Authentik OIDC login."""
    if not settings.oidc_client_id:
        return RedirectResponse(url="/auth/not-configured")

    redirect_uri = settings.app_url.rstrip("/") + "/auth/callback"
    return await oauth.authentik.authorize_redirect(request, redirect_uri)


@router.get("/callback", name="auth_callback")
async def callback(request: Request):
    """Handle OIDC callback from Authentik."""
    try:
        token = await oauth.authentik.authorize_access_token(request)
    except Exception as exc:
        logger.error("OIDC callback error: %s", exc)
        return RedirectResponse(url="/?error=auth_failed")

    user_info = token.get("userinfo") or {}
    sub = user_info.get("sub") or token.get("sub")
    if not sub:
        return RedirectResponse(url="/?error=no_sub")

    # Upsert user in database
    db = SessionLocal()
    try:
        db_user = db.query(User).filter(User.sub == sub).first()
        if not db_user:
            db_user = User(
                sub=sub,
                email=user_info.get("email"),
                name=user_info.get("name") or user_info.get("preferred_username"),
            )
            db.add(db_user)
            db.flush()
            # Create default (empty) notification settings
            db.add(NotificationSetting(user_id=db_user.id))
            db.commit()
        else:
            # Update name/email in case they changed
            db_user.email = user_info.get("email", db_user.email)
            db_user.name = user_info.get("name") or user_info.get("preferred_username", db_user.name)
            db.commit()

        request.session["user"] = {
            "sub": sub,
            "email": db_user.email,
            "name": db_user.name,
            "db_id": db_user.id,
        }
    finally:
        db.close()

    return RedirectResponse(url="/dashboard")


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/")


@router.get("/not-configured")
async def not_configured(request: Request):
    return templates.TemplateResponse(
        request,
        "error.html",
        {
            "title": "OIDC Not Configured",
            "message": (
                "OIDC authentication is not configured. "
                "Please set OIDC_CLIENT_ID, OIDC_CLIENT_SECRET, and "
                "OIDC_DISCOVERY_URL in your .env file."
            ),
        },
    )
