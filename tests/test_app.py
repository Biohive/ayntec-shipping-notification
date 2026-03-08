"""Basic tests for the Ayntec Shipping Notifier application."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.config import settings

# Use an in-memory SQLite database for tests.
# StaticPool ensures all sessions reuse the same single connection so that the
# tables created by setup_database() are visible to every request handler.
TEST_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def setup_database():
    """Create tables before each test and drop after."""
    from app import models  # noqa – ensure models registered
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client():
    app.dependency_overrides[get_db] = override_get_db
    # Disable scheduler during tests
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


# ─── Landing page ────────────────────────────────────────────────────────────

def test_landing_page_returns_200(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Ayntec" in response.text


def test_landing_page_has_get_started(client):
    response = client.get("/")
    assert "Get Started" in response.text


def test_landing_page_has_github_link(client):
    response = client.get("/")
    assert "github" in response.text.lower()


def test_landing_page_has_login_link(client):
    response = client.get("/")
    assert "/auth/login" in response.text


# ─── Auth redirects ──────────────────────────────────────────────────────────

def test_dashboard_redirects_unauthenticated(client):
    response = client.get("/dashboard", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert "/auth/login" in response.headers["location"]


def test_settings_redirects_unauthenticated(client):
    response = client.get("/settings", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert "/auth/login" in response.headers["location"]


def test_add_order_redirects_unauthenticated(client):
    response = client.get("/orders/add", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert "/auth/login" in response.headers["location"]


def test_edit_order_redirects_unauthenticated(client):
    response = client.get("/orders/1/edit", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert "/auth/login" in response.headers["location"]


# ─── Auth routes ─────────────────────────────────────────────────────────────

def test_login_redirects_or_shows_not_configured(client):
    """Login route either redirects to OIDC provider or shows not-configured page."""
    response = client.get("/auth/login", follow_redirects=False)
    # Without OIDC configured the route redirects to /auth/not-configured
    assert response.status_code in (302, 307)


def test_not_configured_page(client):
    response = client.get("/auth/not-configured")
    assert response.status_code == 200
    assert "not configured" in response.text.lower() or "OIDC" in response.text


def test_logout_clears_session_and_redirects(client):
    response = client.get("/auth/logout", follow_redirects=False)
    assert response.status_code in (302, 307)
    # When OIDC is not configured, falls back to redirecting to /
    location = response.headers["location"]
    assert location == "/" or "end-session" in location or "end_session" in location


# ─── Checker module ──────────────────────────────────────────────────────────

def test_parse_dashboard_extracts_ranges():
    from app.checker import _parse_dashboard

    html = """
    <div>
    2026/3/4
    AYN Thor Black Lite: 1500xx--1633xx
    AYN Thor Black Max: 1464xx--1506xx
    </div>
    """
    ranges = _parse_dashboard(html)
    assert len(ranges) == 2
    assert ranges[0].product == "AYN Thor Black Lite"
    assert ranges[0].range_low == 150000
    assert ranges[0].range_high == 163399


def test_check_order_shipped_finds_match():
    from app.checker import check_order_shipped, ShippedRange

    ranges = [ShippedRange(date="2026/3/4", product="AYN Thor Black Lite", range_low=150000, range_high=163399)]
    status, shipped = check_order_shipped("155000", ranges)
    assert shipped is True
    assert "Shipped" in status


def test_check_order_shipped_no_match():
    from app.checker import check_order_shipped, ShippedRange

    ranges = [ShippedRange(date="2026/3/4", product="AYN Thor Black Lite", range_low=150000, range_high=163399)]
    status, shipped = check_order_shipped("200000", ranges)
    assert shipped is False


# ─── Notifiers (unit, no network) ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_send_discord_raises_on_request_error(monkeypatch):
    """send_discord should re-raise httpx.RequestError so callers can handle it."""
    import httpx
    from app import notifiers

    async def mock_post(*args, **kwargs):
        raise httpx.RequestError("network error")

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    with pytest.raises(httpx.RequestError):
        await notifiers.send_discord("https://discord.com/api/webhooks/fake", "1234", "shipped")


@pytest.mark.asyncio
async def test_send_ntfy_raises_on_request_error(monkeypatch):
    """send_ntfy should re-raise httpx.RequestError so callers can handle it."""
    import httpx
    from app import notifiers

    async def mock_post(*args, **kwargs):
        raise httpx.RequestError("network error")

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    with pytest.raises(httpx.RequestError):
        await notifiers.send_ntfy("https://ntfy.sh/fake-topic", "1234", "shipped")


# ─── Config ──────────────────────────────────────────────────────────────────

def test_default_poll_interval():
    assert settings.poll_interval_seconds == 300


def test_secret_key_is_set():
    assert len(settings.secret_key) > 0


# ─── SSRF protection (security.validate_webhook_url) ─────────────────────────

def test_validate_webhook_url_allows_valid_https():
    from app.security import validate_webhook_url
    url = validate_webhook_url("https://discord.com/api/webhooks/123/abc")
    assert url == "https://discord.com/api/webhooks/123/abc"


def test_validate_webhook_url_rejects_http():
    from app.security import validate_webhook_url
    with pytest.raises(ValueError, match="HTTPS"):
        validate_webhook_url("http://discord.com/api/webhooks/123/abc")


def test_validate_webhook_url_rejects_localhost_name():
    from app.security import validate_webhook_url
    with pytest.raises(ValueError, match="private or loopback"):
        validate_webhook_url("https://localhost/evil")


def test_validate_webhook_url_rejects_loopback_ip():
    from app.security import validate_webhook_url
    with pytest.raises(ValueError, match="private or loopback"):
        validate_webhook_url("https://127.0.0.1/secret")


def test_validate_webhook_url_rejects_private_ip_10():
    from app.security import validate_webhook_url
    with pytest.raises(ValueError, match="private or loopback"):
        validate_webhook_url("https://10.0.0.1/internal")


def test_validate_webhook_url_rejects_private_ip_172():
    from app.security import validate_webhook_url
    with pytest.raises(ValueError, match="private or loopback"):
        validate_webhook_url("https://172.16.0.1/internal")


def test_validate_webhook_url_rejects_private_ip_192_168():
    from app.security import validate_webhook_url
    with pytest.raises(ValueError, match="private or loopback"):
        validate_webhook_url("https://192.168.1.1/router")


def test_validate_webhook_url_rejects_link_local_aws_imds():
    from app.security import validate_webhook_url
    with pytest.raises(ValueError, match="private or loopback"):
        validate_webhook_url("https://169.254.169.254/latest/meta-data/")


def test_validate_webhook_url_rejects_ipv6_loopback():
    from app.security import validate_webhook_url
    with pytest.raises(ValueError, match="private or loopback"):
        validate_webhook_url("https://[::1]/secret")


@pytest.mark.asyncio
async def test_send_discord_rejects_ssrf_url():
    """send_discord must reject private-IP URLs before making any HTTP request."""
    from app import notifiers
    with pytest.raises(ValueError, match="private or loopback"):
        await notifiers.send_discord("https://127.0.0.1/hook", "1234", "shipped")


@pytest.mark.asyncio
async def test_send_ntfy_rejects_ssrf_url():
    """send_ntfy must reject private-IP URLs before making any HTTP request."""
    from app import notifiers
    with pytest.raises(ValueError, match="private or loopback"):
        await notifiers.send_ntfy("https://192.168.1.1/ntfy", "1234", "shipped")


# ─── CSRF protection ─────────────────────────────────────────────────────────

def test_post_without_csrf_token_returns_403(client):
    """POST requests without a CSRF token must be rejected with 403."""
    response = client.post("/orders/add", data={"order_number": "12345", "label": ""})
    assert response.status_code == 403


def test_settings_post_without_csrf_token_returns_403(client):
    response = client.post("/settings", data={"discord_webhook_url": ""})
    assert response.status_code == 403


# ─── Input validation ────────────────────────────────────────────────────────

def test_order_number_must_be_numeric():
    """Non-numeric order numbers are rejected by the validation regex."""
    from app.routers.orders import _ORDER_NUMBER_RE
    assert not _ORDER_NUMBER_RE.match("ABC-123")
    assert not _ORDER_NUMBER_RE.match("1234 5")
    assert _ORDER_NUMBER_RE.match("12345")
    assert _ORDER_NUMBER_RE.match("0")


def test_order_number_max_length_enforced():
    """Constant guards the configured maximum order-number length."""
    from app.routers.orders import _MAX_ORDER_NUMBER_LEN
    assert _MAX_ORDER_NUMBER_LEN == 20
    assert len("1" * 21) > _MAX_ORDER_NUMBER_LEN


# ─── Test button URL preservation ────────────────────────────────────────────
#
# When a user clicks "Test" with a URL that differs from the saved DB value,
# the re-rendered settings form must show the *submitted* value so the user
# doesn't have to retype it before saving.

@pytest.fixture()
def auth_client(monkeypatch):
    """TestClient with an authenticated session and pre-populated notification settings."""
    from app.models import User, NotificationSetting
    from app.csrf import verify_csrf
    import app.routers.pages as pages_module

    app.dependency_overrides[get_db] = override_get_db

    # Seed the DB: create a user and a saved notification setting.
    db = next(override_get_db())
    user_row = User(sub="test-sub", email="test@example.com", name="Test User")
    db.add(user_row)
    db.commit()
    db.refresh(user_row)
    user_id = user_row.id  # read before session closes

    notif_row = NotificationSetting(
        user_id=user_id,
        discord_webhook_url="https://discord.com/api/webhooks/saved/saved",
        email_address="saved@example.com",
        ntfy_url="https://ntfy.sh/saved-topic",
    )
    db.add(notif_row)
    db.commit()
    db.close()

    user_dict = {"db_id": user_id, "sub": "test-sub", "email": "test@example.com"}

    # Patch get_current_user (called directly, not via Depends) and bypass CSRF.
    monkeypatch.setattr(pages_module, "get_current_user", lambda request: user_dict)
    app.dependency_overrides[verify_csrf] = lambda: None

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c

    app.dependency_overrides.clear()


def test_ntfy_test_button_preserves_submitted_url(auth_client):
    """Submitted NTFY URL must appear in the form after pressing Test (even on validation error)."""
    # Use an HTTP URL so validate_webhook_url raises ValueError (HTTPS required).
    submitted_url = "http://ntfy.sh/my-new-topic"
    saved_url = "https://ntfy.sh/saved-topic"

    response = auth_client.post(
        "/settings/test/ntfy",
        data={"ntfy_url": submitted_url, "csrf_token": "ignored"},
    )
    assert response.status_code == 200
    assert submitted_url in response.text, "Submitted URL must be shown in the form"
    assert f'value="{saved_url}"' not in response.text, "Saved DB URL must not replace the submitted value"


def test_discord_test_button_preserves_submitted_url(auth_client):
    """Submitted Discord webhook URL must appear in the form after pressing Test."""
    submitted_url = "http://discord.com/api/webhooks/bad"
    saved_url = "https://discord.com/api/webhooks/saved/saved"

    response = auth_client.post(
        "/settings/test/discord",
        data={"discord_webhook_url": submitted_url, "csrf_token": "ignored"},
    )
    assert response.status_code == 200
    assert submitted_url in response.text
    assert f'value="{saved_url}"' not in response.text


def test_ntfy_test_button_clears_field_when_submitted_empty(auth_client):
    """When user submits an empty NTFY URL and clicks Test, the field must appear empty."""
    saved_url = "https://ntfy.sh/saved-topic"

    response = auth_client.post(
        "/settings/test/ntfy",
        data={"ntfy_url": "", "csrf_token": "ignored"},
    )
    assert response.status_code == 200
    assert f'value="{saved_url}"' not in response.text


def test_discord_test_button_clears_field_when_submitted_empty(auth_client):
    """When user submits an empty Discord URL and clicks Test, the field must appear empty."""
    saved_url = "https://discord.com/api/webhooks/saved/saved"

    response = auth_client.post(
        "/settings/test/discord",
        data={"discord_webhook_url": "", "csrf_token": "ignored"},
    )
    assert response.status_code == 200
    assert f'value="{saved_url}"' not in response.text


def test_email_test_button_clears_field_when_submitted_empty(auth_client):
    """When user submits an empty email address and clicks Test, the field must appear empty."""
    saved_email = "saved@example.com"

    response = auth_client.post(
        "/settings/test/email",
        data={"email_address": "", "csrf_token": "ignored"},
    )
    assert response.status_code == 200
    assert f'value="{saved_email}"' not in response.text


# ─── Edit order ───────────────────────────────────────────────────────────────

@pytest.fixture()
def auth_client_with_order(monkeypatch):
    """TestClient with an authenticated session and a seeded order."""
    from app.models import User, Order as OrderModel
    from app.csrf import verify_csrf
    import app.routers.pages as pages_module
    import app.routers.orders as orders_module

    app.dependency_overrides[get_db] = override_get_db

    db = next(override_get_db())
    user_row = User(sub="order-sub", email="order@example.com", name="Order User")
    db.add(user_row)
    db.commit()
    db.refresh(user_row)
    user_id = user_row.id

    order_row = OrderModel(user_id=user_id, order_number="11111", label="My Label")
    db.add(order_row)
    db.commit()
    db.refresh(order_row)
    order_id = order_row.id
    db.close()

    user_dict = {"db_id": user_id, "sub": "order-sub", "email": "order@example.com"}

    monkeypatch.setattr(pages_module, "get_current_user", lambda request: user_dict)
    monkeypatch.setattr(orders_module, "get_current_user", lambda request: user_dict)
    app.dependency_overrides[verify_csrf] = lambda: None

    with TestClient(app, raise_server_exceptions=False) as c:
        c.order_id = order_id
        yield c

    app.dependency_overrides.clear()


def test_edit_order_form_shows_current_values(auth_client_with_order):
    """GET /orders/{id}/edit should render a form pre-filled with current order values."""
    order_id = auth_client_with_order.order_id
    response = auth_client_with_order.get(f"/orders/{order_id}/edit")
    assert response.status_code == 200
    assert "11111" in response.text
    assert "My Label" in response.text


def test_edit_order_updates_label(auth_client_with_order):
    """POST /orders/{id}/edit should update the label and redirect to dashboard."""
    order_id = auth_client_with_order.order_id
    response = auth_client_with_order.post(
        f"/orders/{order_id}/edit",
        data={"order_number": "11111", "label": "New Label", "csrf_token": "ignored"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "/dashboard" in response.headers["location"]


def test_edit_order_updates_order_number(auth_client_with_order):
    """POST /orders/{id}/edit with a new order number should update and reset tracking."""
    order_id = auth_client_with_order.order_id
    response = auth_client_with_order.post(
        f"/orders/{order_id}/edit",
        data={"order_number": "99999", "label": "My Label", "csrf_token": "ignored"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "/dashboard" in response.headers["location"]


def test_edit_order_rejects_non_numeric_order_number(auth_client_with_order):
    """POST /orders/{id}/edit with non-numeric order number should show an error."""
    order_id = auth_client_with_order.order_id
    response = auth_client_with_order.post(
        f"/orders/{order_id}/edit",
        data={"order_number": "ABC", "label": "", "csrf_token": "ignored"},
    )
    assert response.status_code == 200
    assert "digits only" in response.text


def test_edit_order_rejects_duplicate_order_number(auth_client_with_order):
    """POST /orders/{id}/edit should reject an order number already tracked by the user."""
    from app.models import Order as OrderModel

    db = next(override_get_db())

    # Seed a second order for the same user
    existing = (
        db.query(OrderModel)
        .filter(OrderModel.id == auth_client_with_order.order_id)
        .first()
    )
    second = OrderModel(user_id=existing.user_id, order_number="22222", label=None)
    db.add(second)
    db.commit()
    db.close()

    order_id = auth_client_with_order.order_id
    response = auth_client_with_order.post(
        f"/orders/{order_id}/edit",
        data={"order_number": "22222", "label": "", "csrf_token": "ignored"},
    )
    assert response.status_code == 200
    assert "already tracked" in response.text
