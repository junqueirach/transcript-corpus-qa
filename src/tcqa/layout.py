"""Where the files of one revision live, whatever output layout the user chose.

A revised transcript ``<name>.md`` keeps its log, report and summary either next
to it or in an audit sub-folder (``_auditoria``, ``_audit`` or a name the user
picked). These helpers find them without the caller knowing the layout.
"""
from __future__ import annotations

import json
from pathlib import Path

AUDIT_DIRS = ("_auditoria", "_audit", "_tcqa_audit")


def is_revised(path: Path) -> bool:
    """A revised transcript: Markdown with YAML front matter (raw files have a plain header)."""
    if path.suffix.lower() != ".md":
        return False
    try:
        with open(path, encoding="utf-8") as f:
            return f.readline().strip() == "---"
    except (OSError, UnicodeDecodeError):
        return False


def revised_files(target: Path) -> list[Path]:
    if target.is_file():
        return [target] if is_revised(target) else []
    return sorted(p for p in target.rglob("*.md")
                  if is_revised(p) and not any(part.startswith("_") for part in p.relative_to(target).parts[:-1]))


def log_for(revised: Path, audit_dir: str | None = None) -> Path | None:
    stem = revised.stem
    names = [stem + ".log.jsonl"]
    if stem.endswith(".revised"):
        names.append(stem[: -len(".revised")] + ".revised.log.jsonl")
    folders = [revised.parent] + [revised.parent / d for d in ((audit_dir,) if audit_dir else AUDIT_DIRS)]
    for folder in folders:
        for name in names:
            candidate = folder / name
            if candidate.exists():
                return candidate
    return None


def revised_for_log(log_path: Path) -> Path | None:
    """The revised file a log belongs to: the header's ``file``, next to the log or one level up."""
    try:
        header = json.loads(log_path.read_text(encoding="utf-8").splitlines()[0])
    except (OSError, ValueError, IndexError):
        return None
    name = header.get("file")
    if not name:
        return None
    for folder in (log_path.parent, log_path.parent.parent):
        if (folder / name).exists():
            return folder / name
    return None


def logs_in(target: Path) -> list[Path]:
    return [target] if target.is_file() else sorted(target.rglob("*.log.jsonl"))
