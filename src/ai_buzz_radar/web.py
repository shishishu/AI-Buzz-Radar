import os
from datetime import date
from pathlib import Path

from flask import Flask, abort, render_template

from ai_buzz_radar.models import DATABASE_PATH
from ai_buzz_radar.store import Store


def create_app(database: Path | None = None) -> Flask:
    app = Flask(__name__)
    store = Store(database or Path(os.getenv("RADAR_DB", DATABASE_PATH)))

    @app.after_request
    def protect(response):
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; style-src 'self'; base-uri 'none'; frame-ancestors 'none'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
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

    @app.get("/healthz")
    def health():
        return {"status": "ok"}

    return app
