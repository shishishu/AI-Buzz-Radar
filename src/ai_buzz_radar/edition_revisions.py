"""Stage each edition before publishing, retaining previous evidence when replacing a day."""

import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path
from shutil import copy2, copytree
from tempfile import TemporaryDirectory

from ai_buzz_radar.selection_log import selection_log_path


def _install(files, backups):
    """Install staged files, rolling completed replacements back if a later one fails."""
    installed = []
    try:
        for source, target in files:
            target.parent.mkdir(parents=True, exist_ok=True)
            backup = None
            if target.exists():
                if source.samefile(target):
                    continue
                backup = backups / str(len(installed))
                os.link(target, backup)
            source.replace(target)
            installed.append((target, backup))
    except BaseException:
        for target, backup in reversed(installed):
            if backup is None:
                target.unlink()
            else:
                backup.replace(target)
        raise


def _previous_files(folder, day, current, staging):
    # Keep filenames inside each revision so relative JSON links in the original report work.
    source_files = {
        "edition": folder / "editions" / f"{day}.json",
        "record": current,
        "report": current.with_suffix(".md"),
    }
    previous = {name: path for name, path in source_files.items() if path.exists()}
    signature = hashlib.sha256()
    for name, path in previous.items():
        signature.update(name.encode() + hashlib.sha256(path.read_bytes()).digest())
    revision = Path("revisions") / str(day) / signature.hexdigest()[:16]
    links = {}
    files = []
    for name, path in previous.items():
        dest = revision / ("edition.json" if name == "edition" else path.name)
        saved = staging / dest
        saved.parent.mkdir(parents=True, exist_ok=True)
        copy2(path, saved)
        links[name] = dest.as_posix()
        files.append((saved, current.parent / dest))
    # Only generated reports have links to a preceding revision. Rebase those links in the
    # archived copy while keeping the original JSON and hand-written reports verbatim.
    if "record" in previous and "report" in previous:
        try:
            saved_record = json.loads(current.read_bytes())
        except (UnicodeDecodeError, json.JSONDecodeError):
            saved_record = {}
        older = saved_record.get("supersedes", {}) if isinstance(saved_record, dict) else {}
        if older:
            saved = staging / links["report"]
            report = saved.read_text()
            for target in older.values():
                relative = os.path.relpath(current.parent / target, current.parent / revision)
                report = report.replace(f"]({target})", f"]({relative})")
            saved.write_text(report)
    return links, files


@contextmanager
def edition_workspace(folder, day, record, *, replacing):
    folder = folder.resolve()
    current = selection_log_path(folder, day)
    control = folder.name == "codex-cli" and folder.parent.name == "examples"
    base = folder.parent.parent if control else folder.parent
    base.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".radar-edition-", dir=base) as tmp:
        workspace = Path(tmp)
        site = workspace / folder.name
        if control:
            site = workspace / "examples" / folder.name
            site.parent.mkdir()
            if (folder.parent / "editions").exists():
                (site.parent / "editions").symlink_to(folder.parent / "editions")
        if folder.is_dir():
            copytree(folder, site, copy_function=os.link, symlinks=True)
        else:
            site.mkdir()
        revisions = []
        if replacing:
            links, revisions = _previous_files(folder, day, current, workspace / "previous")
            record["supersedes"] = links
        yield site
        # The edition JSON is also the cache marker. Install its assets and dated pages
        # first, so a retry can safely restore the homepage after an interruption.
        public_files = [
            (path, folder / path.relative_to(site))
            for path in site.rglob("*")
            if path.is_file() and not path.is_symlink()
        ]
        staged_log = selection_log_path(site, day)
        files = [
            *revisions,
            (staged_log, current),
            (staged_log.with_suffix(".md"), current.with_suffix(".md")),
            *sorted(
                public_files,
                key=lambda pair: (
                    pair[1] == folder / "index.html",
                    pair[1].parent == folder / "editions",
                ),
            ),
        ]
        backups = workspace / "backups"
        backups.mkdir()
        _install(files, backups)
