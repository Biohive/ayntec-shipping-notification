"""Page routes: landing, dashboard, settings."""

import logging
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.config import settings
from app.csrf import verify_csrf
from app.database import get_db
from app.models import Order, NotificationSetting, SummaryConfig
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
    notif = (
        db.query(NotificationSetting)
        .filter(NotificationSetting.user_id == user["db_id"])
        .first()
    )
    has_enabled_notif = bool(
        notif
        and (notif.discord_enabled or notif.email_enabled or notif.ntfy_enabled)
    )
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "user": user,
            "orders": orders,
            "poll_minutes": settings.poll_interval_seconds // 60,
            "has_enabled_notif": has_enabled_notif,
        },
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


def _empty_field_response(request, user, notif, field: str, message: str):
    """Return an error response for an empty submission, showing a blank field.

    The submitted value was empty, so we clear *field* on the display object so
    the form does not revert to the stale database value.
    """
    display = notif or NotificationSetting(user_id=user["db_id"])
    setattr(display, field, None)
    return _test_response(request, user, display, message, success=False)


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
        return _empty_field_response(request, user, notif, "discord_webhook_url",
                                     "Enter a Discord webhook URL first.")
    try:
        validate_webhook_url(url, label="Discord webhook URL")
        await send_discord(url, "TEST", "This is a test notification")
        if notif:
            notif.discord_tested = True
            db.commit()
            db.refresh(notif)
            # Set after refresh so the submitted URL appears in the re-rendered form
            # without being persisted (no subsequent commit).
            notif.discord_webhook_url = url
        return _test_response(request, user, notif, "Discord test sent")
    except ValueError as exc:
        if notif:
            # No commit follows, so this only affects the rendered response.
            notif.discord_webhook_url = url
        return _test_response(request, user, notif, str(exc), success=False)
    except Exception:
        if notif:
            notif.discord_tested = False
            db.commit()
            db.refresh(notif)
            notif.discord_webhook_url = url
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
        return _empty_field_response(request, user, notif, "email_address",
                                     "Enter an email address first.")
    try:
        send_email(addr, "TEST", "This is a test notification")
        if notif:
            notif.email_tested = True
            db.commit()
            db.refresh(notif)
            # Set after refresh so the submitted address appears in the re-rendered form
            # without being persisted (no subsequent commit).
            notif.email_address = addr
        return _test_response(request, user, notif, "Email test sent")
    except Exception:
        if notif:
            notif.email_tested = False
            db.commit()
            db.refresh(notif)
            notif.email_address = addr
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
        return _empty_field_response(request, user, notif, "ntfy_url",
                                     "Enter an NTFY URL first.")
    try:
        validate_webhook_url(url, label="NTFY URL")
        await send_ntfy(url, "TEST", "This is a test notification")
        if notif:
            notif.ntfy_tested = True
            db.commit()
            db.refresh(notif)
            # Set after refresh so the submitted URL appears in the re-rendered form
            # without being persisted (no subsequent commit).
            notif.ntfy_url = url
        return _test_response(request, user, notif, "NTFY test sent")
    except ValueError as exc:
        if notif:
            # No commit follows, so this only affects the rendered response.
            notif.ntfy_url = url
        return _test_response(request, user, notif, str(exc), success=False)
    except Exception:
        if notif:
            notif.ntfy_tested = False
            db.commit()
            db.refresh(notif)
            notif.ntfy_url = url
        return _test_response(request, user, notif, "NTFY test failed. Check the URL and try again.", success=False)


@router.get("/settings/summary")
async def summary_settings_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/auth/login")

    notif = (
        db.query(NotificationSetting)
        .filter(NotificationSetting.user_id == user["db_id"])
        .first()
    )

    summary = (
        db.query(SummaryConfig)
        .filter(SummaryConfig.user_id == user["db_id"])
        .first()
    )
    if not summary:
        summary = SummaryConfig(user_id=user["db_id"])
        db.add(summary)
        db.commit()
        db.refresh(summary)

    return templates.TemplateResponse(
        request,
        "summary_config.html",
        {
            "user": user,
            "summary": summary,
            "notif": notif,
            "smtp_configured": bool(settings.smtp_host),
        },
    )


@router.post("/settings/summary")
async def save_summary_settings(
    request: Request,
    _csrf: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
    enabled: bool = Form(False),
    delivery_hour: int = Form(20),
    delivery_minute: int = Form(0),
    use_discord: bool = Form(False),
    use_email: bool = Form(False),
    use_ntfy: bool = Form(False),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/auth/login")

    # Clamp hour/minute to valid ranges
    delivery_hour = max(0, min(23, delivery_hour))
    delivery_minute = max(0, min(59, delivery_minute))

    notif = (
        db.query(NotificationSetting)
        .filter(NotificationSetting.user_id == user["db_id"])
        .first()
    )

    summary = (
        db.query(SummaryConfig)
        .filter(SummaryConfig.user_id == user["db_id"])
        .first()
    )
    if not summary:
        summary = SummaryConfig(user_id=user["db_id"])
        db.add(summary)

    summary.enabled = enabled
    summary.delivery_hour = delivery_hour
    summary.delivery_minute = delivery_minute
    summary.use_discord = use_discord
    summary.use_email = use_email
    summary.use_ntfy = use_ntfy

    db.commit()
    db.refresh(summary)

    return templates.TemplateResponse(
        request,
        "summary_config.html",
        {
            "user": user,
            "summary": summary,
            "notif": notif,
            "smtp_configured": bool(settings.smtp_host),
            "success": "Summary settings saved!",
        },
    )
