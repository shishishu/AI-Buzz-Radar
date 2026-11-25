"""Render evidence-linked editorial figures as self-contained, accessible SVG."""

import re
from math import ceil
from typing import Literal
from unicodedata import east_asian_width
from xml.etree import ElementTree as ET

from pydantic import Field

from ai_buzz_radar.models import Record


class FlowStep(Record):
    actor: str = Field(min_length=1, max_length=12)
    action: str = Field(min_length=1, max_length=14)


class FlowPlot(Record):
    kind: Literal["flow"]
    rows: list[FlowStep] = Field(min_length=2, max_length=8)


class ComparisonRow(Record):
    label: str = Field(min_length=1)
    detail: str = Field(min_length=1)


class ComparisonPlot(Record):
    kind: Literal["comparison"]
    rows: list[ComparisonRow] = Field(min_length=2, max_length=4)


class PercentageRow(Record):
    label: str = Field(min_length=1, max_length=5)
    percent: float = Field(ge=0, le=100)


class PercentageBars(Record):
    kind: Literal["bars"]
    measure: str = Field(min_length=1, max_length=18)
    rows: list[PercentageRow] = Field(min_length=2, max_length=6)


class DeadlinePlot(Record):
    kind: Literal["deadline"]
    seconds: int = Field(gt=0)
    start: str = Field(min_length=1, max_length=9)
    end: str = Field(min_length=1, max_length=9)
    window: str = Field(min_length=1, max_length=18)


class Figure(Record):
    title: str = Field(min_length=2)
    caption: str = Field(min_length=4)
    source_url: str = Field(pattern=r"^https://[^\s#]+#\S+$")
    plot: FlowPlot | PercentageBars | DeadlinePlot | ComparisonPlot = Field(discriminator="kind")


INK = "#24332f"
ACCENT = "#27594d"
RULE = "#aab9b2"


def _text(svg, x, y, value, *, anchor="start", weight="400"):
    text = ET.SubElement(
        svg,
        "text",
        {"x": str(x), "y": str(y), "text-anchor": anchor, "font-weight": weight, "fill": INK},
    )
    text.text = value


def _line(svg, x1, y1, x2, y2, color=RULE):
    ET.SubElement(
        svg,
        "line",
        {"x1": str(x1), "y1": str(y1), "x2": str(x2), "y2": str(y2), "stroke": color},
    )


def _wrap(value, units):
    """Wrap on words or CJK characters; units are half-width glyphs."""
    lines, line, width = [], "", 0
    for token in re.findall(r"[A-Za-z0-9_./-]+|\s+|.", value):
        size = sum(2 if east_asian_width(c) in "WF" else 1 for c in token)
        if width + size > units and line.strip():
            lines.append(line.rstrip())
            line, width = "", 0
        if not line and token.isspace():
            continue
        # An identifier may itself be wider than the column.
        while size > units and token.isascii():
            lines.append(token[:units])
            token, size = token[units:], size - units
        line += token
        width += size
    if line.strip():
        lines.append(line.rstrip())
    return lines


def _columns(svg, plot):
    flow = isinstance(plot, FlowPlot)
    if flow:
        rows = [(r.actor, r.action) for r in plot.rows]
        headers = ("执行者", "任务进展")
    else:
        rows = [(r.label, r.detail) for r in plot.rows]
        headers = ("对照项", "观察结果")
    left = 23 if flow else 4
    _text(svg, left, 19, headers[0], weight="600")
    _text(svg, 128, 19, headers[1], weight="600")
    _line(svg, 5, 27, 315, 27)
    y, previous = 49, None
    for label, detail in rows:
        a, b = _wrap(label, 12 if flow else 14), _wrap(detail, 23)
        if flow:
            if previous is not None:
                _line(svg, 10, previous, 10, y - 5)
            ET.SubElement(svg, "circle", {"cx": "10", "cy": str(y - 5), "r": "3.5", "fill": ACCENT})
            previous = y - 5
        for x, column in ((left, a), (128, b)):
            for i, value in enumerate(column):
                _text(svg, x, y + 20 * i, value)
        y += 20 * max(len(a), len(b)) + 12
        if not flow:
            _line(svg, 5, y - 20, 315, y - 20)
    svg.set("viewBox", f"0 0 320 {y - 12}")
    return "；".join(f"{a}：{b}" for a, b in rows)


def _bars(svg, plot):
    # Keep the zero baseline and label a small number of equally spaced percentage ticks.
    left, span = 82, 182
    tick = max(1, ceil(max(row.percent for row in plot.rows) / 3))
    scale = tick * 3
    bottom = 33 + len(plot.rows) * 34
    svg.set("viewBox", f"0 0 320 {bottom + 27}")
    _text(svg, 4, 20, plot.measure, weight="600")
    for i in range(4):
        x = left + span * i / 3
        _line(svg, x, 31, x, bottom, INK if i == 0 else RULE)
        _text(svg, x, bottom + 19, f"{i * tick}%", anchor="middle")
    for i, row in enumerate(plot.rows):
        y = 39 + 34 * i
        width = span * row.percent / scale
        ET.SubElement(
            svg,
            "rect",
            {"x": str(left), "y": str(y), "width": str(width), "height": "16", "fill": ACCENT},
        )
        _text(svg, left - 8, y + 14, row.label, anchor="end")
        _text(svg, left + width + 5, y + 14, f"{row.percent:g}%", weight="600")
    return "；".join(f"{row.label}：{row.percent:g}%" for row in plot.rows)


def _deadline(svg, plot):
    svg.set("viewBox", "0 0 320 116")
    _text(svg, 8, 22, plot.start, weight="600")
    _text(svg, 312, 22, plot.end, anchor="end", weight="600")
    _line(svg, 10, 50, 310, 50, INK)
    for x in (10, 310):
        _line(svg, x, 40, x, 60, INK)
    _text(svg, 10, 81, "0 秒")
    _text(svg, 310, 81, f"{plot.seconds} 秒上界", anchor="end")
    _text(svg, 160, 111, plot.window, anchor="middle")
    return f"从{plot.start}到{plot.end}，上界为 {plot.seconds} 秒。{plot.window}"


def render_figure(figure: Figure) -> str:
    svg = ET.Element(
        "svg",
        {
            "xmlns": "http://www.w3.org/2000/svg",
            "class": "edition-plot",
            "role": "img",
            "font-family": "system-ui, sans-serif",
            "font-size": "15",
        },
    )
    ET.SubElement(svg, "title").text = figure.title
    description = ET.SubElement(svg, "desc")
    if isinstance(figure.plot, (FlowPlot, ComparisonPlot)):
        details = _columns(svg, figure.plot)
    elif isinstance(figure.plot, PercentageBars):
        details = _bars(svg, figure.plot)
    else:
        details = _deadline(svg, figure.plot)
    description.text = f"{details}。{figure.caption}"
    return ET.tostring(svg, encoding="unicode")
