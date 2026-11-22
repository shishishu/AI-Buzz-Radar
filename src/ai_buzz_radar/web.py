import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime
from pathlib import Path

from flask import Flask, abort, make_response, redirect, render_template, request

from ai_buzz_radar.agent import TIMEZONE
from ai_buzz_radar.models import DATABASE_PATH, launch_key
from ai_buzz_radar.store import Store

COOKIE_NAME = "radar_browser"
BROWSER_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")


def browser_token() -> str | None:
    token = request.cookies.get(COOKIE_NAME, "")
    return token if BROWSER_TOKEN.fullmatch(token) else None


def browser_id(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def view_token(token: str) -> str:
    return hmac.digest(token.encode(), b"radar-feed-view", "sha256").hex()


def set_browser_cookie(response, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=365 * 24 * 60 * 60,
        httponly=True,
        samesite="Lax",
        secure=request.is_secure,
    )


def create_app(database: Path | None = None) -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 4096
    store = Store(database or Path(os.getenv("RADAR_DB", DATABASE_PATH)))

    @app.after_request
    def protect(response):
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; style-src 'self'; script-src 'self'; connect-src 'self'; "
            "base-uri 'none'; frame-ancestors 'none'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.endpoint in {"feed", "view_item", "open_source"}:
            response.headers["Cache-Control"] = "private, no-store"
            response.vary.add("Cookie")
        return response

    @app.get("/")
    def feed():
        existing = browser_token()
        token = existing or secrets.token_urlsafe(32)
        now = datetime.now(TIMEZONE)
        if request.method == "GET":
            store.record_event(browser_id(token), "feed_view", now)
        response = make_response(
            render_template(
                "feed.html",
                edition=store.top_edition(now.date()),
                today=now.date(),
                csrf=view_token(token),
            )
        )
        if existing is None and request.method == "GET":
            set_browser_cookie(response, token)
        return response

    @app.post("/events/view/<int:item_id>")
    def view_item(item_id: int):
        token = browser_token()
        csrf = request.form.get("csrf", "")
        if token is None or not csrf.isascii() or not hmac.compare_digest(csrf, view_token(token)):
            abort(403)
        if store.feed_item(item_id) is None:
            abort(404)
        store.record_event(browser_id(token), "item_view", datetime.now(TIMEZONE), item_id)
        return "", 204

    @app.get("/out/<int:item_id>")
    def open_source(item_id: int):
        story = store.feed_item(item_id)
        key = launch_key(story.launch_url) if story else None
        if key is None:
            abort(404)
        response = redirect(f"https://www.producthunt.com{key}")
        purpose = request.headers.get("Sec-Purpose", request.headers.get("Purpose", ""))
        if request.method == "GET" and "prefetch" not in purpose.lower():
            existing = browser_token()
            token = existing or secrets.token_urlsafe(32)
            store.record_event(browser_id(token), "source_click", datetime.now(TIMEZONE), item_id)
            if existing is None:
                set_browser_cookie(response, token)
        return response

    @app.get("/healthz")
    def health():
        return {"status": "ok"}

    return app
