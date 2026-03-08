"""Order management routes."""

import logging
from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import Order
from app.templates import templates

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/orders", tags=["orders"])


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
    order_number: str = Form(...),
    label: str = Form(""),
    db: Session = Depends(get_db),
):
    user = _require_login(request)
    if not user:
        return RedirectResponse(url="/auth/login")

    order_number = order_number.strip()
    if not order_number:
        return templates.TemplateResponse(
            request,
            "add_order.html",
            {"user": user, "error": "Order number is required."},
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
        label=label.strip() or None,
    )
    db.add(new_order)
    db.commit()
    return RedirectResponse(url="/dashboard", status_code=303)


@router.post("/{order_id}/delete")
async def delete_order(order_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_login(request)
    if not user:
        return RedirectResponse(url="/auth/login")

    order = db.query(Order).filter(Order.id == order_id, Order.user_id == user["db_id"]).first()
    if order:
        db.delete(order)
        db.commit()
    return RedirectResponse(url="/dashboard", status_code=303)


@router.post("/{order_id}/reactivate")
async def reactivate_order(order_id: int, request: Request, db: Session = Depends(get_db)):
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
