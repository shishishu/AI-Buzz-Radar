import hashlib
import hmac
import logging
import os
import re
import secrets
from datetime import date, datetime
from pathlib import Path
from uuid import UUID, uuid4

from flask import Flask, abort, make_response, redirect, render_template, request, url_for
from openai import APIError

from ai_buzz_radar.agent import TIMEZONE, describe_error, open_client, run_research
from ai_buzz_radar.models import DATABASE_PATH, RequestTrace, Selection, start_date
from ai_buzz_radar.store import RequestExists, Store
from ai_buzz_radar.usage import DEFAULT_BUDGET_USD

COOKIE_NAME = "radar_browser"
BROWSER_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")
logger = logging.getLogger(__name__)


def browser_token() -> str | None:
    token = request.cookies.get(COOKIE_NAME, "")
    return token if BROWSER_TOKEN.fullmatch(token) else None


def browser_id(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def form_token(token: str, request_id: str) -> str:
    return hmac.digest(token.encode(), f"radar-request:{request_id}".encode(), "sha256").hex()


def create_app(database: Path | None = None) -> Flask:
    app = Flask(__name__)
    app.config["RADAR_REQUESTS_ENABLED"] = bool(os.environ.get("OPENAI_API_KEY"))
    app.config["MAX_CONTENT_LENGTH"] = 16_384
    store = Store(database or Path(os.getenv("RADAR_DB", DATABASE_PATH)))

    @app.after_request
    def protect(response):
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; style-src 'self'; form-action 'self'; "
            "base-uri 'none'; frame-ancestors 'none'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.path.startswith("/research"):
            response.headers["Cache-Control"] = "private, no-store"
            response.vary.add("Cookie")
        return response

    @app.get("/")
    @app.get("/briefs/<day>")
    def brief(day: str | None = None):
        if day is None:
            selected = store.get()
        else:
            try:
                selected = store.get(date.fromisoformat(day))
            except ValueError:
                abort(404)
            if selected is None:
                abort(404)
        return render_template("brief.html", brief=selected, days=store.days())

    def research_form(
        *, values: dict[str, str] | None = None, error: str | None = None, status: int = 200
    ):
        previous_token = browser_token()
        token = previous_token or secrets.token_urlsafe(32)
        request_id = str(uuid4())
        today = datetime.now(TIMEZONE).date()
        if values is None:
            values = {
                "window_start": start_date(today, 3).isoformat(),
                "window_end": today.isoformat(),
                "topic": "",
            }
        response = make_response(
            render_template(
                "research.html",
                values=values,
                today=today,
                history=store.request_history(browser_id(token)),
                request_id=request_id,
                csrf=form_token(token, request_id),
                enabled=app.config["RADAR_REQUESTS_ENABLED"],
                error=error,
            ),
            status,
        )
        if previous_token is None:
            response.set_cookie(
                COOKIE_NAME,
                token,
                max_age=365 * 24 * 60 * 60,
                httponly=True,
                samesite="Lax",
                secure=request.is_secure,
            )
        return response

    def owned_request(request_id: str) -> RequestTrace:
        token = browser_token()
        trace = store.get_request(request_id) if token else None
        if trace is None or trace.user_id != browser_id(token):
            abort(404)
        return trace

    @app.get("/research")
    def research():
        return research_form()

    @app.post("/research")
    def submit_research():
        token = browser_token()
        request_id = request.form.get("request_id", "")
        csrf = request.form.get("csrf", "")
        if (
            token is None
            or not csrf.isascii()
            or not hmac.compare_digest(csrf, form_token(token, request_id))
        ):
            abort(403)
        try:
            key = UUID(request_id)
            if key.version != 4 or str(key) != request_id:
                abort(400)
        except ValueError:
            abort(400)
        user_id = browser_id(token)
        if store.get_request(request_id) is not None:
            owned_request(request_id)
            return redirect(url_for("research_result", request_id=request_id), code=303)

        values = {name: request.form.get(name, "") for name in Selection.model_fields}
        try:
            selection = Selection.model_validate(values)
            if selection.window_end > datetime.now(TIMEZONE).date():
                raise ValueError("Future end date")
        except ValueError:
            return research_form(
                values=values, error="请检查日期顺序、未来日期和主题长度。", status=400
            )
        if not app.config["RADAR_REQUESTS_ENABLED"]:
            return research_form(values=values, error="服务暂未配置生成凭据。", status=503)

        try:
            with open_client() as client:
                run_research(
                    client,
                    store,
                    selection=selection,
                    budget_usd=DEFAULT_BUDGET_USD,
                    user_id=user_id,
                    request_id=request_id,
                )
        except RequestExists:
            owned_request(request_id)
        except (APIError, RuntimeError, ValueError) as error:
            logger.info("Research request %s: %s", request_id, describe_error(error))
            owned_request(request_id)
        return redirect(url_for("research_result", request_id=request_id), code=303)

    @app.get("/research/<request_id>")
    def research_result(request_id: str):
        trace = owned_request(request_id)
        return render_template(
            "research_result.html", trace=trace, attempt=store.get_attempt(trace.attempt_id)
        )

    @app.get("/research/<request_id>/trace")
    def research_trace(request_id: str):
        return store.export_request(owned_request(request_id))

    @app.get("/healthz")
    def health():
        return {"status": "ok"}

    return app
