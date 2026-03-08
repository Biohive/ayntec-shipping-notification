# Ayntec Shipping Notifier

A web application that lets users track **Ayntec order numbers** and receive instant notifications the moment an order ships — via Discord, Email, or NTFY.

> Orders are checked automatically every **5 minutes**. You'll be notified as soon as the status changes to shipped.

---

## Features

- 🔒 **OIDC login** via [Authentik](https://goauthentik.io/) — no passwords to manage
- 📦 **Track multiple orders** per user
- 🔔 **Multi-channel notifications**: Discord webhooks, Email (SMTP), [NTFY](https://ntfy.sh/)
- ⏱️ **Automatic polling** every 5 minutes per order
- 🎨 **Clean, modern UI** built with Tailwind CSS
- 🐳 **Docker-ready** for easy self-hosting

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
| `SECRET_KEY` | Random hex string (run `python -c "import secrets; print(secrets.token_hex(32))"`) |
| `OIDC_CLIENT_ID` | Authentik application client ID |
| `OIDC_CLIENT_SECRET` | Authentik application client secret |
| `OIDC_DISCOVERY_URL` | Authentik OIDC discovery URL |
| `APP_URL` | Public URL of your deployment |

See [`.env.example`](.env.example) for all available options.

### 3. Run with Docker Compose (recommended)

```bash
docker compose up -d
```

The app is available at `http://localhost:8000`.

### 4. Run locally (development)

```bash
pip install -r requirements.txt
DEBUG=true uvicorn app.main:app --reload
```

---

## Authentik OIDC Setup

1. In Authentik, create a new **OAuth2/OpenID Connect Provider** with:
   - Redirect URI: `https://your-domain.example.com/auth/callback`
   - Scopes: `openid`, `email`, `profile`
2. Create an **Application** linked to that provider.
3. Copy the **Client ID**, **Client Secret**, and **OIDC Discovery URL** into your `.env`.

---

## Notification Channels

| Channel | How to configure |
|---|---|
| **Discord** | Paste a [Discord webhook URL](https://support.discord.com/hc/en-us/articles/228383668) in Settings |
| **Email** | Set `SMTP_*` variables in `.env`, then enter your email in Settings |
| **NTFY** | Enter your [ntfy.sh](https://ntfy.sh/) topic URL in Settings |

---

## Development

```bash
pip install -r requirements.txt
pytest tests/ -v
```

---

## License

MIT
