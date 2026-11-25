"""Daily editorial decision records, stored outside the website's document root."""

import json
import re
from collections import Counter
from datetime import date
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import quote, urlsplit
from uuid import uuid4

from ai_buzz_radar.research_sources import ARXIV_HTML

_AUTO_SUMMARY = "<!-- AI Buzz Radar generated selection summary -->"


def _plain(value):
    return re.sub(r"([\\`*_{}\[\]()#!|<>~])", r"\\\1", " ".join(str(value).split()))


def _link(title, url):
    label = _plain(title)
    if urlsplit(url).scheme not in ("https", "http"):
        return label
    return f"[{label}](<{quote(url, safe=':/?#%&=+@,-._~')}>)"


def _channel_table(recalled, reviews, selected, coarse_channels):
    channels = {"arxiv": set(), "first_party_sites": set()}
    for item in recalled:
        channel = item.get("channel")
        if channel is None:
            channel = "arxiv" if item["source"] == ARXIV_HTML.name else "first_party_sites"
        channels[channel].add(item["url"])

    shortlisted = {item["url"] for item in reviews}
    unavailable = {item["url"] for item in reviews if item["status"] == "source_unavailable"}
    winners = {item["url"] for item in selected}
    table = [
        "| 召回渠道 | 去重召回 | 粗排提名 | 进入精读名单 | 原文可用 | 原文不可用 | 最终入选 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    truncated = []
    for key, label in (("arxiv", "arXiv 索引"), ("first_party_sites", "一手网站索引")):
        urls = channels[key]
        nominated = coarse_channels.get(key, {}).get("nomination_count", "—")
        table.append(
            f"| {label} | {len(urls)} | {nominated} | {len(urls & shortlisted)} "
            f"| {len(urls & (shortlisted - unavailable))} | {len(urls & unavailable)} "
            f"| {len(urls & winners)} |"
        )
        if key in coarse_channels:
            counts = coarse_channels[key]
            overflow = counts["nomination_count"] - counts["shortlist_count"]
            if overflow:
                truncated.append(f"{label} {overflow} 篇")
    count = sum(c["nomination_count"] for c in coarse_channels.values()) if coarse_channels else "—"
    table.append(
        f"| 合计 | {len(set.union(*channels.values()))} | {count} | {len(shortlisted)} "
        f"| {len(shortlisted - unavailable)} | {len(unavailable)} | {len(winners)} |"
    )
    if truncated:
        table.extend(["", "、".join(truncated) + "已获渠道提名，因精读名额已满而止步。"])
    return table


def _daily_summary(record, path):
    recall, coarse, fine = (record[key] for key in ("recall", "coarse", "fine"))
    coarse_items, fine_items = coarse.get("items", []), fine.get("items", [])
    source_counts = Counter(item["source"] for item in recall.get("items", []))
    lines = [
        _AUTO_SUMMARY,
        "",
        f"# {record['day']} 选稿记录",
        "",
        f"[完整候选和逐项决定（JSON）]({path.name})",
        "",
    ]
    previous = record.get("supersedes", {})
    if previous:
        labels = {
            "report": "上一版选稿记录",
            "record": "上一版完整漏斗",
            "edition": "上一版日报稿件",
        }
        lines.extend(
            [
                " · ".join(
                    f"[{label}]({previous[key]})"
                    for key, label in labels.items()
                    if key in previous
                ),
                "",
            ]
        )
    lines.extend(["## 召回", ""])
    if "count" in recall:
        interval = (
            f"{recall['start']} 至 {recall['end']}，"
            if recall.get("start") and recall.get("end")
            else ""
        )
        lines.append(f"{interval}去重后共 {recall['count']} 篇。")
    if source_counts:
        lines.append(
            "来源分布为 "
            + "、".join(f"{_plain(k)}（{v}）" for k, v in source_counts.items())
            + "。"
        )
    if "items" in recall:
        table = _channel_table(
            recall["items"], fine_items, record["selected"], coarse.get("channels", {})
        )
        lines.extend(["", *table])
    if recall.get("warnings"):
        lines.extend(["", "部分来源返回警告。", ""])
        lines.extend(f"- {_plain(warning)}" for warning in recall["warnings"])
    lines += ["", "## 粗排", ""]
    if coarse.get("mode") == "editor_picks":
        lines.append("本次由编辑直接指定三篇，并按指定顺序核对原文。")
    else:
        lines.append(_plain(coarse.get("rule", "")))
        if coarse.get("merge_rule"):
            lines.append(_plain(coarse["merge_rule"]))
        shortlist = sorted(
            (item for item in coarse_items if item["status"] == "shortlisted"),
            key=lambda item: item.get("shortlist_position", 0),
        )
        lines.extend(["", f"合并后共 {len(shortlist)} 篇进入精读，以下按送审顺序列出。", ""])
        for item in shortlist:
            lines.append(f"- {_link(item['title'], item['url'])}　{_plain(item['reason'])}")
        exclusions = Counter(
            item["reason"] for item in coarse_items if item["status"] != "shortlisted"
        )
        if exclusions:
            lines.extend(["", "其余候选按记录的原因汇总。", ""])
            lines.extend(
                f"- {count} 篇　{_plain(reason)}" for reason, count in exclusions.most_common()
            )
    lines.extend(["", "## 精排与入选", "", _plain(fine.get("rule", "")), ""])
    reviews = {item["url"]: item for item in fine_items}
    if fine.get("portfolio_reason"):
        lines.extend(["**组合取舍**　" + _plain(fine["portfolio_reason"]), ""])
    winners = [item["url"] for item in record["selected"]]
    proposed = fine.get("proposed_urls", [])
    if proposed and proposed != winners:
        displaced = [url for url in proposed if url not in winners]
        replacements = [url for url in winners if url not in proposed]
        for label, urls in (("原提议后未刊发", displaced), ("成稿核验后递补", replacements)):
            if urls:
                lines.extend(
                    [label + "：" + "、".join(_link(reviews[u]["title"], u) for u in urls), ""]
                )
    genres = Counter(item["genre"] for item in record["selected"] if item.get("genre"))
    if genres:
        lines.extend(
            ["入选体裁为 " + "、".join(f"{_plain(g)}（{n}）" for g, n in genres.items()) + "。", ""]
        )
    for rank, item in enumerate(record["selected"], 1):
        review = reviews.get(item["url"], {})
        urls = [review.get("evidence_url"), *item.get("evidence_links", [])]
        links = list(dict.fromkeys(url for url in urls if url))
        genre = f"〔{_plain(item['genre'])}〕" if item.get("genre") else ""
        lines.append(
            f"{rank}. {genre}{_link(item['title'], item['url'])}　{_plain(item.get('reason', ''))}"
        )
        if record["mode"] == "editor_picks" and item.get("article_reason"):
            lines.append("   稿件推荐理由为" + _plain(item["article_reason"]))
        if review.get("evidence"):
            lines.append("   原文摘录为「" + _plain(review["evidence"]) + "」。")
        figure = item.get("figure", {})
        if figure.get("status") == "unavailable":
            lines.append("   本篇未配图。" + _plain(figure["reason"]))
        if links:
            lines.append(
                "   " + " · ".join(_link(f"原文证据 {i}", u) for i, u in enumerate(links, 1))
            )
    others = [item for item in fine_items if item["status"] != "selected"]
    if others:
        lines.extend(["", "### 其他精读候选", ""])
        labels = {
            "reserve": "候补",
            "excluded": "未入选",
            "source_unavailable": "取文失败",
            "draft_failed": "成稿核验失败",
        }
        for item in sorted(others, key=lambda entry: entry.get("position", float("inf"))):
            outcome = labels.get(item["status"], item["status"])
            detail = "。".join(_plain(item[key]) for key in ("reason", "error") if item.get(key))
            genre = f" · {_plain(item['genre'])}" if item.get("genre") else ""
            line = f"- {outcome}{genre} · {_link(item['title'], item['url'])}　{detail}"
            if item.get("evidence_url"):
                line += " " + _link("原文证据", item["evidence_url"])
            lines.append(line)
    return "\n".join(lines).rstrip() + "\n"


def _write_atomic(path, content):
    if path.exists() and path.read_bytes() == content.encode("utf-8"):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False)
    temp_path = Path(tmp.name)
    try:
        with tmp:
            tmp.write(content)
        temp_path.replace(path)
    finally:
        temp_path.unlink(missing_ok=True)


def selection_log_path(output: Path, day: date | str) -> Path:
    day = date.fromisoformat(str(day))
    output = output.resolve()
    if output.name == "codex-cli" and output.parent.name == "examples":
        directory = output.parent.parent / "selection-records" / "codex-cli"
    elif output.name == "examples":
        directory = output.parent / "selection-records"
    else:
        directory = output.with_name(f"{output.name}-selection-records")
    return directory / f"{day}.json"


def selection_summary_ready(path, record, *, restore=False):
    """Check generated Markdown against its source JSON and preserve hand-written reports."""
    report = path.with_suffix(".md")
    data = report.read_bytes() if report.is_file() else b""
    if record.get("mode") not in {"automatic", "editor_picks"}:
        return bool(data.strip()) and str(record["day"]).encode() in data
    expected = _daily_summary(record, path)
    if data == expected.encode():
        return True
    marker = _AUTO_SUMMARY.encode()
    if restore:
        if data.strip() and not (data.startswith(marker) or marker.startswith(data.strip())):
            raise ValueError(f"Inspect hand-edited or damaged report before restoring: {report}")
        _write_atomic(report, expected)
        return True
    return False


def save_selection_log(output: Path, record: dict) -> Path:
    """Publish a complete decision record atomically, keeping failed runs separate."""
    path = selection_log_path(output, record["day"])
    if record.get("schema_version") != 1 or record.get("status") not in {"selected", "failed"}:
        raise ValueError("Invalid selection log version or status")
    if not record.get("mode") or not all(
        isinstance(record.get(s), dict) for s in ("recall", "coarse", "fine")
    ):
        raise ValueError("Selection records need a mode and all three stages")
    selected = record.get("selected")
    if not isinstance(selected, list) or any(
        not isinstance(item, dict)
        or not all(isinstance(item.get(key), str) and item[key].strip() for key in ("url", "title"))
        for item in selected
    ):
        raise ValueError("Selected items need titles and source URLs")
    if len({item["url"].rstrip("/") for item in selected}) != len(selected):
        raise ValueError("Duplicate selected article")
    if record["status"] == "failed":
        path = path.parent / "attempts" / f"{path.stem}-{uuid4().hex}.json"
    elif len(selected) != 3:
        raise ValueError("A completed selection needs exactly three articles")
    content = json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if record["status"] == "selected" and record["mode"] in {"automatic", "editor_picks"}:
        summary_path = path.with_suffix(".md")
        if not summary_path.exists() or summary_path.read_text(encoding="utf-8").startswith(
            _AUTO_SUMMARY
        ):
            _write_atomic(summary_path, _daily_summary(record, path))
    _write_atomic(path, content)
    return path
