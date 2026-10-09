"""Logos, icon and app name.

Uploads land in the data volume rather than being referenced by URL, so
branding survives without depending on an external host staying up.

Reading is public. The sign-in page needs the logo and the browser needs the
icon, both before anyone has signed in, and a logo reveals nothing. Writing is
admin only.
"""

from __future__ import annotations


import logging
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response

from app import audit
from app.auth.deps import AdminUser
from app.settings_store import current

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/branding")

KINDS = {"logo", "login_logo", "icon"}

ALLOWED = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
    "image/x-icon": ".ico",
    "image/vnd.microsoft.icon": ".ico",
    "image/gif": ".gif",
}

MAX_BYTES = 4 * 1024 * 1024


def _looks_like(suffix: str, body: bytes) -> bool:
    head = body[:512]
    if suffix == ".png":
        return head.startswith(b"\x89PNG\r\n\x1a\n")
    if suffix == ".jpg":
        return head.startswith(b"\xff\xd8\xff")
    if suffix == ".gif":
        return head.startswith((b"GIF87a", b"GIF89a"))
    if suffix == ".webp":
        return head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    if suffix == ".ico":
        return head[:4] == b"\x00\x00\x01\x00"
    if suffix == ".svg":
        text = body[:4096].decode("utf-8", errors="ignore").lower()
        return "<svg" in text
    return False


def branding_dir() -> Path:
    path = current().data_dir / "branding"
    path.mkdir(parents=True, exist_ok=True)
    return path


def stored(kind: str) -> Path | None:
    matches = sorted(branding_dir().glob(f"{kind}.*"))
    return matches[0] if matches else None


@router.get("")
def list_branding() -> dict:
    """Which marks are set, and the app name."""
    return {
        "app_name": current().app_name,
        # Read before anyone signs in: the sign-in page is the app's face too.
        "accent": current().accent_color or None,
        "theme": current().theme_colors or None,
        "images": {kind: stored(kind) is not None for kind in sorted(KINDS)},
    }


HOME_SIZES = (180, 192, 512)
"""180 is what an iPhone asks for, 192 and 512 what Android does."""

BACKGROUND = "#0b1017"
"""The dark page colour: what a phone shows while the app opens."""


@router.get("/manifest.webmanifest")
def manifest() -> Response:
    """What a phone needs to put the app on its home screen as an app.

    Without one, Add to Home Screen saves a bookmark: the browser's own bars
    stay, and the icon is a screenshot or a letter. With it, the app opens
    full screen under its own name and mark. Nothing here works offline, and
    nothing pretends to: there is no service worker, because a page of live
    streams read from a cache would be a page of stale ones.
    """
    import json

    settings = current()
    name = settings.app_name or "Cartographarr"
    body = {
        "name": name,
        "short_name": name[:12],
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": BACKGROUND,
        "theme_color": BACKGROUND,
        "icons": [
            {"src": f"/api/branding/home-icon/{size}", "sizes": f"{size}x{size}", "type": "image/png", "purpose": "any"}
            for size in (192, 512)
        ],
    }
    return Response(
        json.dumps(body), media_type="application/manifest+json", headers={"Cache-Control": "public, max-age=300"}
    )


def _home_icon(size: int) -> bytes:
    """A square PNG for a home screen: the uploaded icon on the page colour,
    or the app's own pin when there is none that can be drawn from."""
    import io

    from PIL import Image, ImageDraw

    canvas = Image.new("RGB", (size, size), BACKGROUND)
    path = stored("icon")
    if path is not None and path.suffix != ".svg":
        try:
            with Image.open(path) as mark:
                mark = mark.convert("RGBA")
                # Inset, because both phones crop the corners into a rounded
                # shape and a mark drawn to the edge loses its own.
                mark.thumbnail((int(size * 0.8), int(size * 0.8)), Image.Resampling.LANCZOS)
                canvas.paste(mark, ((size - mark.width) // 2, (size - mark.height) // 2), mark)
                out = io.BytesIO()
                canvas.save(out, "PNG", optimize=True)
                return out.getvalue()
        except Exception:  # noqa: BLE001 - an unreadable upload falls back to the pin
            canvas = Image.new("RGB", (size, size), BACKGROUND)
    # The pin from the browser tab's icon, drawn at this size.
    accent = current().accent_color or "#22d3ee"
    draw = ImageDraw.Draw(canvas)
    u = size / 32
    cx, top = size / 2, 6 * u
    draw.ellipse((cx - 8 * u, top, cx + 8 * u, top + 16 * u), fill=accent)
    draw.polygon([(cx - 7 * u, top + 11 * u), (cx + 7 * u, top + 11 * u), (cx, 28 * u)], fill=accent)
    draw.ellipse((cx - 3.2 * u, top + 4.8 * u, cx + 3.2 * u, top + 11.2 * u), fill=BACKGROUND)
    out = io.BytesIO()
    canvas.save(out, "PNG", optimize=True)
    return out.getvalue()


@router.get("/home-icon/{size}")
def home_icon(size: int) -> Response:
    if size not in HOME_SIZES:
        raise HTTPException(404, f"Sizes made: {', '.join(map(str, HOME_SIZES))}")
    return Response(_home_icon(size), media_type="image/png", headers={"Cache-Control": "public, max-age=300"})


@router.get("/{kind}")
def get_branding(kind: str):
    if kind not in KINDS:
        raise HTTPException(404, f"Unknown image. Try one of: {', '.join(sorted(KINDS))}")
    path = stored(kind)
    if path is None:
        raise HTTPException(404, "Not set")
    # Short cache: a logo changes rarely, but when it does the change should
    # show up without anyone being told to hard refresh. Sandboxed, so an SVG
    # opened directly cannot run script as this site; as an <img> it never can.
    return FileResponse(
        path,
        headers={
            "Cache-Control": "public, max-age=300",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.put("/{kind}")
async def put_branding(kind: str, admin: AdminUser, file: UploadFile) -> dict:
    if kind not in KINDS:
        raise HTTPException(404, f"Unknown image. Try one of: {', '.join(sorted(KINDS))}")

    suffix = ALLOWED.get((file.content_type or "").lower())
    if suffix is None:
        raise HTTPException(
            400, "Needs to be a PNG, JPEG, WebP, SVG, GIF or ICO image"
        )

    body = await file.read()
    if len(body) > MAX_BYTES:
        raise HTTPException(400, f"Too large. Keep it under {MAX_BYTES // 1024 // 1024} MB.")
    if not body:
        raise HTTPException(400, "That file is empty")
    # The browser's label is whatever it says; check the file is what it claims.
    if not _looks_like(suffix, body):
        raise HTTPException(400, "That file is not the image type it claims to be")

    # Replace rather than accumulate: one file per mark, whatever its type.
    for existing in branding_dir().glob(f"{kind}.*"):
        existing.unlink(missing_ok=True)

    (branding_dir() / f"{kind}{suffix}").write_bytes(body)
    audit.record(
        admin, "branding.upload", f"Uploaded a new {kind.replace('_', ' ')}",
        target=kind, detail={"bytes": len(body), "type": file.content_type},
    )
    return {"kind": kind, "bytes": len(body)}


@router.delete("/{kind}")
def clear_branding(kind: str, admin: AdminUser) -> dict:
    if kind not in KINDS:
        raise HTTPException(404, "Unknown image")
    removed = False
    for existing in branding_dir().glob(f"{kind}.*"):
        existing.unlink(missing_ok=True)
        removed = True
    if removed:
        audit.record(admin, "branding.clear", f"Removed the {kind.replace('_', ' ')}", target=kind)
    return {"kind": kind, "removed": removed}


def reset_all() -> None:
    """Used by tests and a fresh install."""
    shutil.rmtree(branding_dir(), ignore_errors=True)
