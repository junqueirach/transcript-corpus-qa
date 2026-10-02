"""Front matter: a deliberately small YAML subset, read and written without
any external library.

Supported: ``key: value`` lines where value is a quoted string, a bare string,
an integer, a float, ``true``/``false``/``null`` or a one-line list
``[a, "b c", 3]``. Comments after ``#`` (outside quotes) are ignored. Nested
blocks are not supported on purpose: the revision rules forbid them.

Also reads the *legacy* plain header used by raw transcripts::

    Título: ...
    Autor: ...
    (blank line)
    body
"""
from __future__ import annotations

import re
from typing import Any

FM_DELIM = "---"
LEGACY_LINE = re.compile(r"^([A-Za-zÀ-ÿ_][\w À-ÿ]*?):\s?(.*)$")


class FrontmatterError(ValueError):
    pass


def _strip_comment(line: str) -> str:
    out, quote = [], None
    for ch in line:
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
        elif ch in ('"', "'"):
            quote = ch
            out.append(ch)
        elif ch == "#":
            break
        else:
            out.append(ch)
    return "".join(out).rstrip()


def parse_scalar(text: str) -> Any:
    t = text.strip()
    if t == "" or t == "null" or t == "~":
        return None
    if t == "true":
        return True
    if t == "false":
        return False
    if len(t) >= 2 and t[0] == t[-1] and t[0] in ('"', "'"):
        inner = t[1:-1]
        if t[0] == '"':
            inner = inner.replace('\\"', '"').replace("\\\\", "\\")
        return inner
    if re.fullmatch(r"[+-]?\d+", t):
        return int(t)
    if re.fullmatch(r"[+-]?\d+\.\d+", t):
        return float(t)
    return t


def _split_list(inner: str) -> list[str]:
    items, cur, quote = [], [], None
    for ch in inner:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = None
        elif ch in ('"', "'"):
            quote = ch
            cur.append(ch)
        elif ch == ",":
            items.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if "".join(cur).strip():
        items.append("".join(cur))
    return [i for i in items]


def parse_value(text: str) -> Any:
    t = text.strip()
    if t.startswith("[") and t.endswith("]"):
        inner = t[1:-1].strip()
        if not inner:
            return []
        return [parse_scalar(i) for i in _split_list(inner)]
    return parse_scalar(t)


def parse_frontmatter_block(block: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for number, raw_line in enumerate(block.splitlines(), start=1):
        line = _strip_comment(raw_line)
        if not line.strip():
            continue
        if line.startswith((" ", "\t")):
            raise FrontmatterError(f"front matter line {number}: nested blocks are not allowed")
        if ":" not in line:
            raise FrontmatterError(f"front matter line {number}: expected 'key: value'")
        key, _, value = line.partition(":")
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise FrontmatterError(f"front matter line {number}: bad key {key!r}")
        if key in data:
            raise FrontmatterError(f"front matter line {number}: duplicate key {key!r}")
        data[key] = parse_value(value)
    return data


def split_document(text: str) -> tuple[dict[str, Any] | None, str, str]:
    """Split a document into (front matter dict or None, body, kind).

    ``kind`` is 'yaml' when a ``---`` block was found, 'legacy' when a plain
    ``Key: value`` header was found, 'none' otherwise. The body never includes
    the header. A UTF-8 BOM is tolerated.
    """
    text = text.lstrip("﻿").replace("\r\n", "\n")
    lines = text.split("\n")
    if lines and lines[0].strip() == FM_DELIM:
        for i in range(1, len(lines)):
            if lines[i].strip() == FM_DELIM:
                block = "\n".join(lines[1:i])
                body = "\n".join(lines[i + 1:])
                return parse_frontmatter_block(block), body.lstrip("\n"), "yaml"
        raise FrontmatterError("front matter opened with '---' but never closed")
    # legacy header: consecutive 'Key: value' lines, then a blank line
    header: dict[str, Any] = {}
    i = 0
    while i < len(lines) and lines[i].strip():
        m = LEGACY_LINE.match(lines[i])
        if not m:
            break
        header[m.group(1).strip()] = m.group(2).strip()
        i += 1
    if header and i < len(lines) and not lines[i].strip() and len(header) >= 2:
        return header, "\n".join(lines[i + 1:]).lstrip("\n"), "legacy"
    return None, text, "none"


def format_value(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(format_value(v) for v in value) + "]"
    s = str(value)
    needs_quotes = (s == "" or s != s.strip() or any(c in s for c in ':#[]{}",\'') or s in ("true", "false", "null", "~")
                    or re.fullmatch(r"[+-]?\d+(\.\d+)?", s) is not None)
    if needs_quotes:
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return s


def dump_frontmatter(data: dict[str, Any]) -> str:
    lines = [FM_DELIM]
    for key, value in data.items():
        lines.append(f"{key}: {format_value(value)}")
    lines.append(FM_DELIM)
    return "\n".join(lines) + "\n"


def join_document(data: dict[str, Any], body: str) -> str:
    return dump_frontmatter(data) + "\n" + body.lstrip("\n")
