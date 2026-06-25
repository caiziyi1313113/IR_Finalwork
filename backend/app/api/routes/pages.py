from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core.config import get_settings

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[2] / "templates"))
templates.env.auto_reload = True
ROOT_DIR = Path(__file__).resolve().parents[4]
IMAGE_DIR = ROOT_DIR / "image"
SUPPORTED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
EXCLUDED_IMAGE_KEYWORDS = ("\u6821\u5fbd", "logo", "emblem")


def _get_favicon_url() -> str:
    if IMAGE_DIR.exists():
        for image_path in sorted(IMAGE_DIR.iterdir(), key=lambda item: item.name):
            if not image_path.is_file() or image_path.suffix.lower() not in SUPPORTED_IMAGE_SUFFIXES:
                continue

            stem = image_path.stem.strip().lower()
            original_name = image_path.name.strip().lower()
            if any(keyword in stem or keyword in original_name for keyword in EXCLUDED_IMAGE_KEYWORDS):
                return f"/images/{quote(image_path.name)}"

    hero_images = _collect_hero_images()
    return hero_images[0] if hero_images else ""


def _set_no_store(response: HTMLResponse) -> HTMLResponse:
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


def _collect_hero_images() -> list[str]:
    if not IMAGE_DIR.exists():
        return []

    hero_images: list[str] = []
    for image_path in sorted(IMAGE_DIR.iterdir(), key=lambda item: item.name):
        if not image_path.is_file() or image_path.suffix.lower() not in SUPPORTED_IMAGE_SUFFIXES:
            continue

        stem = image_path.stem.strip().lower()
        original_name = image_path.name.strip().lower()
        if any(keyword in stem or keyword in original_name for keyword in EXCLUDED_IMAGE_KEYWORDS):
            continue

        hero_images.append(f"/images/{quote(image_path.name)}")
    return hero_images


@router.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    settings = get_settings()
    return _set_no_store(templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "search_request_timeout_ms": settings.search_request_timeout_ms,
            "hero_images": _collect_hero_images(),
            "favicon_url": _get_favicon_url(),
        },
    ))


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    return _set_no_store(templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "hero_images": _collect_hero_images(),
            "favicon_url": _get_favicon_url(),
        },
    ))


@router.get("/profile-setup", response_class=HTMLResponse)
async def profile_setup_page(request: Request) -> HTMLResponse:
    return _set_no_store(templates.TemplateResponse(
        "profile_setup.html",
        {
            "request": request,
            "favicon_url": _get_favicon_url(),
        },
    ))


@router.get("/favicon.ico", include_in_schema=False)
async def favicon() -> RedirectResponse:
    return RedirectResponse(url=_get_favicon_url() or "/")
