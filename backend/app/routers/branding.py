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
from fastapi.responses import FileResponse

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
        "images": {kind: stored(kind) is not None for kind in sorted(KINDS)},
    }


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
