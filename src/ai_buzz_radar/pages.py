"""Publish a verified daily edition to the radar directory of the personal Pages site."""

import hashlib
import os
import subprocess
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from ai_buzz_radar.editions import Edition, verify_publication
from ai_buzz_radar.models import DATABASE_PATH
from ai_buzz_radar.store import Store

REPOSITORY = "https://github.com/shishishu/shishishu.github.io.git"
SITE_URL = "https://shishishu.github.io/radar/"


def push_pages(html, day, repository=REPOSITORY):
    # A fresh clone keeps the operator's homepage checkout and unrelated edits untouched.
    with TemporaryDirectory(prefix="radar-pages-") as work:
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}

        def git(*args):
            subprocess.run(["git", *args], cwd=work, env=env, check=True, timeout=120)

        filenames = ("index.html", f"agent-reading-{day}.html")
        git(
            "clone",
            "--depth=1",
            "--branch=main",
            "--filter=blob:none",
            "--no-checkout",
            repository,
            ".",
        )
        git("sparse-checkout", "set", "--no-cone", *(f"/radar/{name}" for name in filenames))
        git("checkout", "main")
        directory = Path(work) / "radar"
        if directory.is_symlink():
            raise ValueError("Unexpected symlink at radar/")
        directory.mkdir(exist_ok=True)
        changed = []
        for name in filenames:
            path = directory / name
            if path.is_symlink():
                raise ValueError(f"Unexpected symlink at radar/{name}")
            if not path.exists() or path.read_bytes() != html:
                path.write_bytes(html)
                changed.append(f"radar/{name}")
        if changed:
            git("add", "--", *changed)
            git(
                "-c",
                "user.name=AI Buzz Radar",
                "-c",
                "user.email=shishishu@users.noreply.github.com",
                "commit",
                "-m",
                f"Publish Agent Systems Daily for {day}",
                "--",
                *changed,
            )
            # A concurrent push fails normally; the timer retries from the new remote HEAD.
            git("push", "origin", "HEAD:main")


def wait_for_pages(html, day):
    digest = hashlib.sha256(html).hexdigest()
    pending = {SITE_URL, f"{SITE_URL}agent-reading-{day}.html"}
    deadline = time.monotonic() + 300
    while pending:
        for url in tuple(pending):
            try:
                with urlopen(
                    f"{url}?edition={digest[:16]}&check={time.time_ns()}", timeout=15
                ) as r:
                    if hashlib.sha256(r.read()).hexdigest() == digest:
                        pending.remove(url)
            except (HTTPError, URLError, TimeoutError) as exc:
                print(f"Awaiting GitHub Pages at {url}: {exc}", flush=True)
        if pending:
            if time.monotonic() >= deadline:
                raise RuntimeError(f"HTML not yet verified on GitHub Pages: {sorted(pending)}")
            time.sleep(10)


def publish_pages(output, day, record):
    with Store(Path(os.getenv("RADAR_DB", DATABASE_PATH))).run_lock():
        data = (output / "editions" / f"{day}.json").read_bytes()
        if record.get("edition_sha256") != hashlib.sha256(data).hexdigest():
            raise ValueError("Selection record does not match the edition being published")
        verify_publication(output, Edition.model_validate_json(data), record, latest=True)
        html = (output / "index.html").read_bytes()
        push_pages(html, day)
    wait_for_pages(html, day)
    print(f"Verified {day} at {SITE_URL}", flush=True)
