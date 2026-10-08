"""Serve the built browser app only when the hosted deployment enables it."""

from __future__ import annotations

import os
import re
from pathlib import Path

from fastapi import FastAPI
from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles


_HASHED_ASSET = re.compile(r"^assets/[^/]+-[A-Za-z0-9_-]{8,}\.[^/]+$")


class BrowserApp(StaticFiles):
    async def get_response(self, path: str, scope):
        if path == ".":
            path = ""
        # Never turn a missing API route, private file, or missing JS chunk into
        # a successful HTML response. StaticFiles also enforces directory bounds.
        segments = path.split("/")
        if segments[0] in {"api", "health"} or any(part.startswith(".") for part in segments if part):
            raise HTTPException(status_code=404)
        try:
            response = await super().get_response(path, scope)
        except HTTPException as error:
            if error.status_code != 404 or scope["method"] not in {"GET", "HEAD"} or Path(path).suffix or segments[0] == "assets":
                raise
            response = await super().get_response("index.html", scope)
        if response.headers.get("content-type", "").startswith("text/html"):
            response.headers["Cache-Control"] = "no-store"
        elif _HASHED_ASSET.fullmatch(path):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


def mount_static_web(app: FastAPI, directory: str | None = None) -> bool:
    """Append the web app after API routes; keep local Compose API unchanged."""
    selected = directory if directory is not None else os.getenv("STATIC_WEB_DIR", "")
    if not selected:
        return False
    root = Path(selected).resolve()
    if not (root / "index.html").is_file():
        raise RuntimeError("STATIC_WEB_DIR must contain the built browser app")
    app.mount("/", BrowserApp(directory=str(root), html=True), name="browser-app")
    return True
