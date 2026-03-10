"""Page routes: landing, dashboard, settings."""

import logging
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.config import settings
from app.csrf import verify_csrf
from app.database import get_db
from app.models import Order, NotificationSetting, SummaryConfig, ShipmentSnapshot
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


# ---------------------------------------------------------------------------
# Public order checker (no login required)
# ---------------------------------------------------------------------------

# Import here to avoid circular imports — orders router owns this list.
_ORDER_NUMBER_RE = re.compile(r"^\d{1,10}$")

# Must stay in sync with KNOWN_DEVICE_TYPES in routers/orders.py
_CHECKER_DEVICE_TYPES: list[str] = [
    "AYN Thor Black Lite",
    "AYN Thor Black Base",
    "AYN Thor Black Pro",
    "AYN Thor Black Max",
    "AYN Thor White Pro",
    "AYN Thor White Max",
    "AYN Thor Rainbow Pro",
    "AYN Thor Rainbow Max",
    "AYN Thor Clear Purple Pro",
    "AYN Thor Clear Purple Max",
]
_CHECKER_DEVICE_TYPES_LOWER = {d.lower() for d in _CHECKER_DEVICE_TYPES}


def _format_range(low: int, high: int) -> str:
    """Format a stored integer range back into prefix+xx notation.

    E.g. (150000, 163399) → '1500xx–1633xx'
    """
    wc = 0
    for exp in range(1, 8):
        divisor = 10 ** exp
        if low % divisor == 0 and (high + 1) % divisor == 0:
            wc = exp
        else:
            break
    if wc == 0:
        return f"{low}\u2013{high}"
    divisor = 10 ** wc
    xs = "x" * wc
    return f"{low // divisor}{xs}\u2013{high // divisor}{xs}"


@router.get("/check")
async def order_checker_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    latest = (
        db.query(ShipmentSnapshot)
        .order_by(ShipmentSnapshot.fetched_at.desc())
        .first()
    )
    return templates.TemplateResponse(
        request,
        "check.html",
        {
            "user": user,
            "device_types": _CHECKER_DEVICE_TYPES,
            "last_updated": latest.fetched_at if latest else None,
            "poll_minutes": settings.poll_interval_seconds // 60,
        },
    )


@router.get("/api/check")
async def api_check_order(
    request: Request,
    product: str = "",
    order: str = "",
    db: Session = Depends(get_db),
):
    """Public JSON endpoint: check whether an order number has shipped.

    Returns ``{"shipped": bool, "date": str|null, "last_fetched": str|null}``.
    """
    product = product.strip()
    order = order.strip().lstrip("#")

    if not product or product.lower() not in _CHECKER_DEVICE_TYPES_LOWER:
        return JSONResponse({"error": "Invalid product"}, status_code=400)

    if not order or not _ORDER_NUMBER_RE.match(order):
        return JSONResponse({"error": "Order number must be 1–10 digits"}, status_code=400)

    snapshots = (
        db.query(ShipmentSnapshot)
        .filter(ShipmentSnapshot.product == product)
        .all()
    )

    if not snapshots:
        latest = db.query(ShipmentSnapshot).order_by(ShipmentSnapshot.fetched_at.desc()).first()
        return JSONResponse({
            "shipped": False,
            "date": None,
            "last_fetched": latest.fetched_at.strftime("%Y/%m/%d %H:%M UTC") if latest else None,
            "latest_range": None,
        })

    try:
        order_int = int(order)
    except ValueError:
        return JSONResponse({"error": "Invalid order number"}, status_code=400)

    order_digits = len(str(order_int))
    matched_date: str | None = None

    for snap in snapshots:
        range_digits = len(str(snap.range_low))
        candidate = order_int
        if order_digits < range_digits:
            factor = 10 ** (range_digits - order_digits)
            candidate = order_int * factor

        if snap.range_low <= candidate <= snap.range_high:
            matched_date = snap.date
            break

    last_fetched = snapshots[0].fetched_at.strftime("%Y/%m/%d %H:%M UTC") if snapshots else None

    # Find the most recent snapshot to show as context when not yet shipped
    latest_snap = max(snapshots, key=lambda s: s.range_high)
    latest_range_str = _format_range(latest_snap.range_low, latest_snap.range_high)

    return JSONResponse({
        "shipped": matched_date is not None,
        "date": matched_date,
        "last_fetched": last_fetched,
        "latest_range": latest_range_str,
        "latest_range_date": latest_snap.date,
    })


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


def _to_24h(hour_12: int, ampm: str) -> int:
    """Convert 12-hour clock (1–12, AM/PM) to 24-hour (0–23)."""
    hour_12 = max(1, min(12, hour_12))
    if ampm.upper() == "AM":
        return 0 if hour_12 == 12 else hour_12
    else:
        return 12 if hour_12 == 12 else hour_12 + 12


def _to_12h(hour_24: int) -> tuple[int, str]:
    """Convert 24-hour (0–23) to 12-hour clock (1–12, AM/PM)."""
    if hour_24 == 0:
        return 12, "AM"
    elif hour_24 < 12:
        return hour_24, "AM"
    elif hour_24 == 12:
        return 12, "PM"
    else:
        return hour_24 - 12, "PM"


def _summary_template_context(user, summary, notif, smtp_configured: bool, **extra) -> dict:
    """Build the template context dict for summary_config.html."""
    hour_12, ampm = _to_12h(summary.delivery_hour)
    return {
        "user": user,
        "summary": summary,
        "notif": notif,
        "smtp_configured": smtp_configured,
        "delivery_hour_12": hour_12,
        "delivery_ampm": ampm,
        **extra,
    }


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
        _summary_template_context(user, summary, notif, bool(settings.smtp_host)),
    )


@router.post("/settings/summary")
async def save_summary_settings(
    request: Request,
    _csrf: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
    enabled: bool = Form(False),
    delivery_hour_12: int = Form(8),
    delivery_minute: int = Form(0),
    delivery_ampm: str = Form("PM"),
    delivery_timezone: str = Form("America/New_York"),
    use_discord: bool = Form(False),
    use_email: bool = Form(False),
    use_ntfy: bool = Form(False),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/auth/login")

    # Convert 12h → 24h local time
    delivery_hour_24 = _to_24h(delivery_hour_12, delivery_ampm)
    delivery_minute = (max(0, min(59, delivery_minute)) // 15) * 15

    # Validate timezone (fall back to UTC on unrecognised value)
    try:
        ZoneInfo(delivery_timezone)
        tz_str = delivery_timezone
    except (ZoneInfoNotFoundError, KeyError):
        logger.warning("Unrecognised timezone %r submitted by user %s – falling back to UTC", delivery_timezone, user.get("db_id"))
        tz_str = "UTC"

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
    summary.delivery_hour = delivery_hour_24
    summary.delivery_minute = delivery_minute
    summary.timezone = tz_str
    summary.use_discord = use_discord
    summary.use_email = use_email
    summary.use_ntfy = use_ntfy

    db.commit()
    db.refresh(summary)

    return templates.TemplateResponse(
        request,
        "summary_config.html",
        _summary_template_context(
            user, summary, notif, bool(settings.smtp_host),
            success="Summary settings saved!",
        ),
    )
