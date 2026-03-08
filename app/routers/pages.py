"""Page routes: landing, dashboard, settings."""

import logging
from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.models import Order, NotificationSetting
from app.templates import templates

logger = logging.getLogger(__name__)

router = APIRouter(tags=["pages"])


@router.get("/")
async def landing(request: Request):
    user = get_current_user(request)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "user": user,
            "github_repo_url": settings.github_repo_url,
        },
    )


@router.get("/dashboard")
async def dashboard(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/auth/login")

    orders = (
        db.query(Order)
        .filter(Order.user_id == user["db_id"])
        .order_by(Order.created_at.desc())
        .all()
    )
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"user": user, "orders": orders},
    )


@router.get("/settings")
async def settings_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/auth/login")

    notif = (
        db.query(NotificationSetting)
        .filter(NotificationSetting.user_id == user["db_id"])
        .first()
    )
    if not notif:
        notif = NotificationSetting(user_id=user["db_id"])
        db.add(notif)
        db.commit()
        db.refresh(notif)

    return templates.TemplateResponse(
        request,
        "settings.html",
        {"user": user, "notif": notif},
    )


@router.post("/settings")
async def save_settings(
    request: Request,
    db: Session = Depends(get_db),
    discord_webhook_url: str = Form(""),
    discord_enabled: bool = Form(False),
    email_address: str = Form(""),
    email_enabled: bool = Form(False),
    ntfy_url: str = Form(""),
    ntfy_enabled: bool = Form(False),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/auth/login")

    notif = (
        db.query(NotificationSetting)
        .filter(NotificationSetting.user_id == user["db_id"])
        .first()
    )
    if not notif:
        notif = NotificationSetting(user_id=user["db_id"])
        db.add(notif)

    notif.discord_webhook_url = discord_webhook_url.strip() or None
    notif.discord_enabled = discord_enabled and bool(discord_webhook_url.strip())
    notif.email_address = email_address.strip() or None
    notif.email_enabled = email_enabled and bool(email_address.strip())
    notif.ntfy_url = ntfy_url.strip() or None
    notif.ntfy_enabled = ntfy_enabled and bool(ntfy_url.strip())

    db.commit()
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "user": user,
            "notif": notif,
            "success": "Settings saved!",
        },
    )
