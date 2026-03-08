"""Shared Jinja2 templates instance with global variables."""

from fastapi.templating import Jinja2Templates
from app.config import settings

templates = Jinja2Templates(directory="templates")

# Make app-wide variables available in every template
templates.env.globals["app_name"] = settings.app_name
templates.env.globals["github_repo_url"] = settings.github_repo_url
