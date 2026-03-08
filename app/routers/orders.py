"""Order management routes."""

import logging
import re
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.csrf import verify_csrf
from app.database import get_db
from app.models import Order
from app.templates import templates

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/orders", tags=["orders"])

# Maximum lengths for user-supplied order fields
_MAX_ORDER_NUMBER_LEN = 20
_MAX_LABEL_LEN = 100

# Order numbers are numeric only
_ORDER_NUMBER_RE = re.compile(r"^\d+$")


def _require_login(request: Request):
    user = get_current_user(request)
    if not user:
        return None
    return user


@router.get("/add")
async def add_order_form(request: Request):
    user = _require_login(request)
    if not user:
        return RedirectResponse(url="/auth/login")
    return templates.TemplateResponse(request, "add_order.html", {"user": user})


@router.post("/add")
async def add_order(
    request: Request,
    _csrf: None = Depends(verify_csrf),
    order_number: str = Form(...),
    label: str = Form(""),
    db: Session = Depends(get_db),
):
    user = _require_login(request)
    if not user:
        return RedirectResponse(url="/auth/login")

    order_number = order_number.strip()
    label = label.strip()

    if not order_number:
        return templates.TemplateResponse(
            request,
            "add_order.html",
            {"user": user, "error": "Order number is required."},
        )

    if not _ORDER_NUMBER_RE.match(order_number):
        return templates.TemplateResponse(
            request,
            "add_order.html",
            {"user": user, "error": "Order number must contain digits only."},
        )

    if len(order_number) > _MAX_ORDER_NUMBER_LEN:
        return templates.TemplateResponse(
            request,
            "add_order.html",
            {"user": user, "error": f"Order number must be at most {_MAX_ORDER_NUMBER_LEN} digits."},
        )

    if len(label) > _MAX_LABEL_LEN:
        return templates.TemplateResponse(
            request,
            "add_order.html",
            {"user": user, "error": f"Label must be at most {_MAX_LABEL_LEN} characters."},
        )

    # Check for duplicate
    existing = (
        db.query(Order)
        .filter(Order.user_id == user["db_id"], Order.order_number == order_number, Order.active == True)  # noqa: E712
        .first()
    )
    if existing:
        return templates.TemplateResponse(
            request,
            "add_order.html",
            {"user": user, "error": "Order already tracked."},
        )

    new_order = Order(
        user_id=user["db_id"],
        order_number=order_number,
        label=label or None,
    )
    db.add(new_order)
    db.commit()
    return RedirectResponse(url="/dashboard", status_code=303)


@router.get("/{order_id}/edit")
async def edit_order_form(
    order_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_login(request)
    if not user:
        return RedirectResponse(url="/auth/login")

    order = db.query(Order).filter(Order.id == order_id, Order.user_id == user["db_id"]).first()
    if not order:
        return RedirectResponse(url="/dashboard", status_code=303)

    return templates.TemplateResponse(request, "edit_order.html", {"user": user, "order": order})


@router.post("/{order_id}/edit")
async def edit_order(
    order_id: int,
    request: Request,
    _csrf: None = Depends(verify_csrf),
    order_number: str = Form(...),
    label: str = Form(""),
    db: Session = Depends(get_db),
):
    user = _require_login(request)
    if not user:
        return RedirectResponse(url="/auth/login")

    order = db.query(Order).filter(Order.id == order_id, Order.user_id == user["db_id"]).first()
    if not order:
        return RedirectResponse(url="/dashboard", status_code=303)

    order_number = order_number.strip()
    label = label.strip()

    if not order_number:
        return templates.TemplateResponse(
            request,
            "edit_order.html",
            {"user": user, "order": order, "error": "Order number is required."},
        )

    if not _ORDER_NUMBER_RE.match(order_number):
        return templates.TemplateResponse(
            request,
            "edit_order.html",
            {"user": user, "order": order, "error": "Order number must contain digits only."},
        )

    if len(order_number) > _MAX_ORDER_NUMBER_LEN:
        return templates.TemplateResponse(
            request,
            "edit_order.html",
            {"user": user, "order": order, "error": f"Order number must be at most {_MAX_ORDER_NUMBER_LEN} digits."},
        )

    if len(label) > _MAX_LABEL_LEN:
        return templates.TemplateResponse(
            request,
            "edit_order.html",
            {"user": user, "order": order, "error": f"Label must be at most {_MAX_LABEL_LEN} characters."},
        )

    # If the order number changed, check it isn't already tracked by this user
    if order_number != order.order_number:
        duplicate = (
            db.query(Order)
            .filter(
                Order.user_id == user["db_id"],
                Order.order_number == order_number,
                Order.id != order_id,
                Order.active == True,  # noqa: E712
            )
            .first()
        )
        if duplicate:
            return templates.TemplateResponse(
                request,
                "edit_order.html",
                {"user": user, "order": order, "error": "Order already tracked."},
            )

        # Reset tracking state since we're now monitoring a different order number
        order.order_number = order_number
        order.last_status = None
        order.shipped = False
        order.notified = False
        order.active = True

    order.label = label or None
    db.commit()
    return RedirectResponse(url="/dashboard", status_code=303)


@router.post("/{order_id}/delete")
async def delete_order(
    order_id: int,
    request: Request,
    _csrf: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    user = _require_login(request)
    if not user:
        return RedirectResponse(url="/auth/login")

    order = db.query(Order).filter(Order.id == order_id, Order.user_id == user["db_id"]).first()
    if order:
        db.delete(order)
        db.commit()
    return RedirectResponse(url="/dashboard", status_code=303)


@router.post("/{order_id}/reactivate")
async def reactivate_order(
    order_id: int,
    request: Request,
    _csrf: None = Depends(verify_csrf),
    db: Session = Depends(get_db),
):
    """Re-enable notifications for an order that already shipped."""
    user = _require_login(request)
    if not user:
        return RedirectResponse(url="/auth/login")

    order = db.query(Order).filter(Order.id == order_id, Order.user_id == user["db_id"]).first()
    if order:
        order.shipped = False
        order.notified = False
        order.last_status = None
        db.commit()
    return RedirectResponse(url="/dashboard", status_code=303)
