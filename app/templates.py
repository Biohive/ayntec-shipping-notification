"""Shared Jinja2 templates instance with global variables."""

import subprocess

from fastapi.templating import Jinja2Templates
from app import __version__
from app.config import settings
from app.csrf import get_csrf_token


def _get_git_commit() -> str:
    """Return the short git commit hash, or empty string if unavailable."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        return ""


templates = Jinja2Templates(directory="templates")

# Make app-wide variables available in every template
templates.env.globals["app_name"] = settings.app_name
templates.env.globals["github_repo_url"] = settings.github_repo_url
templates.env.globals["app_version"] = __version__
templates.env.globals["git_commit"] = _get_git_commit()

# Expose CSRF token generation to all templates:
#   <input type="hidden" name="csrf_token" value="{{ csrf_token(request) }}">
templates.env.globals["csrf_token"] = get_csrf_token
