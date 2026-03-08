# Ayntec Shipping Notifier

A web application that lets users track **Ayntec order numbers** and receive instant notifications the moment an order ships — via Discord, Email, or NTFY.

Orders are checked automatically on a configurable interval (default: every **5 minutes**). You'll be notified as soon as the status changes to shipped.

---

## Features

- 📦 **Track multiple orders** per user, with optional friendly labels
- 🔔 **Multi-channel notifications**: Discord webhooks, Email (SMTP), [NTFY](https://ntfy.sh/)
- 🧪 **Test notifications** from the Settings page before saving, without needing to wait for a real shipment
- 🔒 **CSRF protection** on all state-changing forms
- 🛡️ **SSRF protection** — webhook and NTFY URLs are validated against private/loopback ranges before any outbound request is made
- 🗃️ **Automatic schema migrations** — the database upgrades itself on startup; no manual SQL required
- 🏷️ **Version + commit hash** displayed in the UI footer
- ⚙️ **Configurable polling interval** via `POLL_INTERVAL_SECONDS`

---

## Quick Start

### 1. Clone and configure

```bash
git clone https://github.com/Biohive/ayntec-shipping-notification
cd ayntec-shipping-notification
cp .env.example .env
# Edit .env with your settings
```

### 2. Set required environment variables

| Variable | Description |
|---|---|
| `SECRET_KEY` | Random hex string — run `python -c "import secrets; print(secrets.token_hex(32))"` to generate one. If omitted, a temporary key is generated on each start (all sessions invalidated on restart). |
| `OIDC_CLIENT_ID` | Authentik application client ID |
| `OIDC_CLIENT_SECRET` | Authentik application client secret |
| `OIDC_DISCOVERY_URL` | Authentik OIDC discovery URL |
| `APP_URL` | Public URL of your deployment (used for OIDC redirect URI) |

See [`.env.example`](.env.example) for all available options, including optional variables.

### 3. Run with Docker Compose (recommended)

```bash
docker compose up -d
```

The app is available at `http://localhost:8000`. The SQLite database is persisted in `./data/`.

### 4. Run locally (development)

```bash
pip install -r requirements.txt
DEBUG=true uvicorn app.main:app --reload
```

The API docs (Swagger UI) are available at `/api/docs` when `DEBUG=true`.

---

## Authentik OIDC Setup

1. In Authentik, create a new **OAuth2/OpenID Connect Provider** with:
   - Redirect URI: `https://your-domain.example.com/auth/callback`
   - Scopes: `openid`, `email`, `profile`
2. Enable `Signing Key`
3. Create an **Application** linked to that provider.
4. Copy the **Client ID**, **Client Secret**, and **OIDC Discovery URL** into your `.env`.

---

## Notification Channels

| Channel | How to configure |
|---|---|
| **Discord** | Paste a [Discord webhook URL](https://support.discord.com/hc/en-us/articles/228383668) in Settings |
| **Email** | Set `SMTP_*` variables in `.env`, then enter your email address in Settings. The Settings page shows a warning if SMTP is not configured. |
| **NTFY** | Enter your [ntfy.sh](https://ntfy.sh/) topic URL in Settings |

Each channel has a **Test** button on the Settings page. Clicking it sends a test notification using the URL currently in the input field — you don't need to save first.

> **Note:** Discord and NTFY URLs must use `https://` and must not point to private or loopback addresses (SSRF protection).

---

## Environment Variables Reference

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | *(auto-generated)* | Session signing key — set a stable value to persist sessions across restarts |
| `APP_URL` | `http://localhost:8000` | Public base URL, used for OIDC redirect URI |
| `APP_NAME` | `Ayntec Shipping Notifier` | Application name shown in the UI |
| `DEBUG` | `false` | Enable debug logging and Swagger UI |
| `DATABASE_URL` | `sqlite:///./data/app.db` | SQLAlchemy database URL |
| `OIDC_CLIENT_ID` | | Authentik OAuth2 client ID |
| `OIDC_CLIENT_SECRET` | | Authentik OAuth2 client secret |
| `OIDC_DISCOVERY_URL` | | OIDC `.well-known/openid-configuration` URL |
| `POLL_INTERVAL_SECONDS` | `300` | How often (seconds) to check the Ayntec dashboard |
| `AYNTEC_DASHBOARD_URL` | `https://www.ayntec.com/pages/shipment-dashboard` | Ayntec dashboard URL scraped for shipped order ranges |
| `SMTP_HOST` | | SMTP server hostname — leave blank to disable email |
| `SMTP_PORT` | `587` | SMTP port (STARTTLS) |
| `SMTP_USER` | | SMTP username |
| `SMTP_PASS` | | SMTP password |
| `SMTP_FROM` | | Sender address (defaults to `SMTP_USER` if blank) |
| `GITHUB_REPO_URL` | `https://github.com/Biohive/ayntec-shipping-notification` | Repository link shown in the UI |

---

## Development

```bash
pip install -r requirements.txt
pytest tests/ -v
```

---

## License

MIT
