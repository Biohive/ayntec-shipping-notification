"""Page routes: landing, dashboard, settings."""

import logging
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.config import settings
from app.csrf import verify_csrf
from app.database import get_db
from app.models import Order, NotificationSetting
from app.notifiers import send_discord, send_ntfy, send_email
from app.security import validate_webhook_url
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
        {"user": user, "orders": orders, "poll_minutes": settings.poll_interval_seconds // 60},
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
        {"user": user, "notif": notif, "smtp_configured": bool(settings.smtp_host)},
    )


@router.post("/settings")
async def save_settings(
    request: Request,
    _csrf: None = Depends(verify_csrf),
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

    # Validate and store Discord webhook URL
    new_discord_url = discord_webhook_url.strip() or None
    if new_discord_url:
        try:
            validate_webhook_url(new_discord_url, label="Discord webhook URL")
        except ValueError as exc:
            return templates.TemplateResponse(
                request,
                "settings.html",
                {"user": user, "notif": notif, "smtp_configured": bool(settings.smtp_host), "error": str(exc)},
            )
    if new_discord_url != notif.discord_webhook_url:
        notif.discord_tested = False
    notif.discord_webhook_url = new_discord_url
    notif.discord_enabled = discord_enabled and bool(new_discord_url)

    new_email = email_address.strip() or None
    if new_email != notif.email_address:
        notif.email_tested = False
    notif.email_address = new_email
    notif.email_enabled = email_enabled and bool(new_email)

    # Validate and store NTFY URL
    new_ntfy_url = ntfy_url.strip() or None
    if new_ntfy_url:
        try:
            validate_webhook_url(new_ntfy_url, label="NTFY URL")
        except ValueError as exc:
            return templates.TemplateResponse(
                request,
                "settings.html",
                {"user": user, "notif": notif, "smtp_configured": bool(settings.smtp_host), "error": str(exc)},
            )
    if new_ntfy_url != notif.ntfy_url:
        notif.ntfy_tested = False
    notif.ntfy_url = new_ntfy_url
    notif.ntfy_enabled = ntfy_enabled and bool(new_ntfy_url)

    db.commit()
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "user": user,
            "notif": notif,
            "smtp_configured": bool(settings.smtp_host),
            "success": "Settings saved!",
        },
    )


async def _get_notif_or_redirect(request, db):
    user = get_current_user(request)
    if not user:
        return None, None, RedirectResponse(url="/auth/login")
    notif = (
        db.query(NotificationSetting)
        .filter(NotificationSetting.user_id == user["db_id"])
        .first()
    )
    return user, notif, None


def _test_response(request, user, notif, message, success=True):
    key = "success" if success else "error"
    return templates.TemplateResponse(
        request, "settings.html",
        {"user": user, "notif": notif, "smtp_configured": bool(settings.smtp_host), key: message},
    )


@router.post("/settings/test/discord")
async def test_discord(
    request: Request,
    _csrf: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
    discord_webhook_url: str = Form(""),
):
    user, notif, redirect = await _get_notif_or_redirect(request, db)
    if redirect:
        return redirect
    url = discord_webhook_url.strip()
    if not url:
        return _test_response(request, user, notif or NotificationSetting(user_id=user["db_id"]),
                              "Enter a Discord webhook URL first.", success=False)
    try:
        validate_webhook_url(url, label="Discord webhook URL")
        await send_discord(url, "TEST", "This is a test notification")
        if notif:
            notif.discord_tested = True
            db.commit()
            db.refresh(notif)
        return _test_response(request, user, notif, "Discord test sent")
    except ValueError as exc:
        return _test_response(request, user, notif, str(exc), success=False)
    except Exception:
        if notif:
            notif.discord_tested = False
            db.commit()
            db.refresh(notif)
        return _test_response(request, user, notif, "Discord test failed. Check the webhook URL and try again.", success=False)


@router.post("/settings/test/email")
async def test_email(
    request: Request,
    _csrf: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
    email_address: str = Form(""),
):
    user, notif, redirect = await _get_notif_or_redirect(request, db)
    if redirect:
        return redirect
    addr = email_address.strip()
    if not addr:
        return _test_response(request, user, notif or NotificationSetting(user_id=user["db_id"]),
                              "Enter an email address first.", success=False)
    try:
        send_email(addr, "TEST", "This is a test notification")
        if notif:
            notif.email_tested = True
            db.commit()
            db.refresh(notif)
        return _test_response(request, user, notif, "Email test sent")
    except Exception:
        if notif:
            notif.email_tested = False
            db.commit()
            db.refresh(notif)
        return _test_response(request, user, notif, "Email test failed. Check your SMTP settings.", success=False)


@router.post("/settings/test/ntfy")
async def test_ntfy(
    request: Request,
    _csrf: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
    ntfy_url: str = Form(""),
):
    user, notif, redirect = await _get_notif_or_redirect(request, db)
    if redirect:
        return redirect
    url = ntfy_url.strip()
    if not url:
        return _test_response(request, user, notif or NotificationSetting(user_id=user["db_id"]),
                              "Enter an NTFY URL first.", success=False)
    try:
        validate_webhook_url(url, label="NTFY URL")
        await send_ntfy(url, "TEST", "This is a test notification")
        if notif:
            notif.ntfy_tested = True
            db.commit()
            db.refresh(notif)
        return _test_response(request, user, notif, "NTFY test sent")
    except ValueError as exc:
        return _test_response(request, user, notif, str(exc), success=False)
    except Exception:
        if notif:
            notif.ntfy_tested = False
            db.commit()
            db.refresh(notif)
        return _test_response(request, user, notif, "NTFY test failed. Check the URL and try again.", success=False)
