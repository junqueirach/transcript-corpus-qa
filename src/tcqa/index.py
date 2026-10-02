"""``tcqa index``: rebuild the corpus index from the files' front matter, or
audit an existing index for the inconsistencies the method forbids.

* ``tcqa index build FOLDER --out indice.csv``  one row per revised file,
  computed fields recomputed from the text, durations normalised.
* ``tcqa index audit indice.csv``  checks an index (old or new format) and
  lists duplicated rows, mixed duration formats, unlinked translations, flags
  that contradict the rules, inconsistent channel names and unsafe filenames.
"""
from __future__ import annotations

import argparse
import csv
import re
from collections import defaultdict
from pathlib import Path

from .classify import compute
from .textnorm import analyze

COLUMNS = [
    "arquivo", "pasta", "titulo", "tipo", "canal", "data", "duracao", "idioma", "derivado_de",
    "classe_calculada", "classe_qualidade", "falantes", "trechos_incertos", "trechos_irrecuperaveis",
    "pct_irrecuperavel", "apto_rag", "apto_finetuning", "audio_recuperavel", "raw_sha256", "revisado_em",
]
WINDOWS_FORBIDDEN = '<>:"\\|?*'
TRANSLATION_SUFFIX = re.compile(r"\s*\((PT-BR|pt-BR|EN|en)\)\s*$")


# ---------------------------------------------------------------- helpers

def normalise_duration(value) -> str | None:
    """'9:10' -> '00:09:10'; '2:19:23' -> '02:19:23'; '06:45' -> '00:06:45'.
    Two parts are read as MM:SS. Returns None when the value is not a duration."""
    if value is None:
        return None
    text = str(value).strip()
    if not re.fullmatch(r"\d{1,2}(:\d{1,2}){1,2}", text):
        return None
    parts = [int(p) for p in text.split(":")]
    if len(parts) == 2:
        parts = [0] + parts
    h, m, s = parts
    if m > 59 or s > 59:
        return None
    return f"{h:02d}:{m:02d}:{s:02d}"


def sanitize_filename(title: str) -> str:
    """Readable file name from a title: '/' becomes ' - ', characters Windows
    forbids are dropped, runs of spaces collapse, trailing dots/spaces go."""
    name = title.replace("/", " - ")
    name = "".join(ch for ch in name if ch not in WINDOWS_FORBIDDEN)
    name = re.sub(r"\s+", " ", name).strip().rstrip(".")
    return name


def _bool(value) -> str:
    return "true" if value is True else "false" if value is False else ""


# ------------------------------------------------------------------ build

def build_rows(folder: Path) -> tuple[list[dict], list[str]]:
    rows, problems = [], []
    for path in sorted(folder.rglob("*.md")):
        if path.name.upper() in ("README.MD", "CLAUDE.MD", "LEIA-ME.MD"):
            continue
        text = path.read_text(encoding="utf-8")
        doc = analyze(text)
        if doc.header_kind != "yaml":
            continue  # raw files have no front matter and are not indexed
        fm = doc.frontmatter or {}
        comp = compute(doc, derived=fm.get("derivado_de") is not None, language=fm.get("idioma"))
        rel = path.relative_to(folder)
        duration = normalise_duration(fm.get("duracao"))
        if fm.get("duracao") and duration is None:
            problems.append(f"{rel}: duration {fm.get('duracao')!r} is not a time")
        for key in ("classe_calculada", "trechos_incertos", "trechos_irrecuperaveis", "pct_irrecuperavel"):
            if key in fm and fm[key] != getattr(comp, key):
                problems.append(f"{rel}: front matter {key}={fm[key]!r} but the text gives {getattr(comp, key)!r}")
        expected_name = sanitize_filename(str(fm.get("titulo") or path.stem))
        if sanitize_filename(path.stem) != path.stem:
            problems.append(f"{rel}: file name needs sanitising -> {sanitize_filename(path.stem)!r}")
        falantes = fm.get("falantes")
        rows.append({
            "arquivo": path.name,
            "pasta": str(rel.parent).replace("\\", "/") if str(rel.parent) != "." else "",
            "titulo": fm.get("titulo", ""),
            "tipo": fm.get("tipo", ""),
            "canal": fm.get("canal", ""),
            "data": fm.get("data", ""),
            "duracao": duration or "",
            "idioma": fm.get("idioma", ""),
            "derivado_de": fm.get("derivado_de") or "",
            "classe_calculada": comp.classe_calculada,
            "classe_qualidade": fm.get("classe_qualidade", ""),
            "falantes": ";".join(falantes) if isinstance(falantes, list) else (falantes or ""),
            "trechos_incertos": comp.trechos_incertos,
            "trechos_irrecuperaveis": comp.trechos_irrecuperaveis,
            "pct_irrecuperavel": comp.pct_irrecuperavel,
            "apto_rag": _bool(fm.get("apto_rag")),
            "apto_finetuning": _bool(fm.get("apto_finetuning")),
            "audio_recuperavel": _bool(fm.get("audio_recuperavel")),
            "raw_sha256": fm.get("raw_sha256", "") or "",
            "revisado_em": fm.get("revisado_em", "") or "",
        })
    return rows, problems


def write_index(rows: list[dict], out: Path) -> None:
    with open(out, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


# ------------------------------------------------------------------ audit

def audit_index(rows: list[dict]) -> list[str]:
    """Return human-readable inconsistencies found in an index (any format)."""
    findings: list[str] = []
    if not rows:
        return ["index is empty"]
    columns = set(rows[0].keys())
    for col in ("idioma", "derivado_de", "raw_sha256", "pct_irrecuperavel", "classe_calculada"):
        if col not in columns:
            findings.append(f"column '{col}' is missing (old format): {col} cannot be verified")

    # durations
    for r in rows:
        d = r.get("duracao", "")
        if d and normalise_duration(d) != d:
            findings.append(f"{r['arquivo']}: duration {d!r} is not HH:MM:SS (should be {normalise_duration(d)!r})")

    # translations and links
    # a source and its translation share the file stem up to the '(PT-BR)' suffix
    by_title: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_title[TRANSLATION_SUFFIX.sub("", Path(r["arquivo"]).stem).strip()].append(r)
    for r in rows:
        is_translation = bool(TRANSLATION_SUFFIX.search(Path(r["arquivo"]).stem))
        linked = bool(r.get("derivado_de"))
        if is_translation and not linked:
            findings.append(f"{r['arquivo']}: looks like a translation but has no derivado_de link")
        if is_translation and r.get("apto_finetuning") == "true":
            findings.append(f"{r['arquivo']}: translation marked apto_finetuning=true (rule R6/D4 says false)")
        if not is_translation and not linked:
            klass = r.get("classe_qualidade", "")
            flag = r.get("apto_finetuning", "")
            if klass in ("A", "B") and flag == "false":
                findings.append(f"{r['arquivo']}: class {klass} source file with apto_finetuning=false (rule says true unless language is out of scope)")
            if klass == "C" and flag == "true":
                findings.append(f"{r['arquivo']}: class C with apto_finetuning=true")
        if "classe_calculada" in columns and r.get("classe_calculada") and r.get("classe_qualidade") \
                and r["classe_calculada"] != r["classe_qualidade"]:
            findings.append(f"{r['arquivo']}: classe_qualidade {r['classe_qualidade']} differs from classe_calculada {r['classe_calculada']} (needs override_motivo in the file)")

    # pairs must agree on class and counts
    for title, group in by_title.items():
        if len(group) > 1:
            for key in ("classe_qualidade", "trechos_incertos", "trechos_irrecuperaveis", "duracao", "data"):
                values = {g.get(key, "") for g in group}
                if len(values) > 1:
                    findings.append(f"'{title}': rows disagree on {key}: {sorted(values)}")

    # channel consistency inside a folder
    by_folder: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        by_folder[r.get("pasta", "")].add(r.get("canal", ""))
    for folder, channels in by_folder.items():
        if len(channels) > 1:
            findings.append(f"folder '{folder}': several channel names {sorted(channels)}")

    # filenames
    for r in rows:
        stem = Path(r["arquivo"]).stem
        title = TRANSLATION_SUFFIX.sub("", r.get("titulo", "")).strip()
        if re.search(r"\s{2,}", stem):
            findings.append(f"{r['arquivo']}: double space in file name")
        if title and "/" in title:
            expected = sanitize_filename(title)
            base = TRANSLATION_SUFFIX.sub("", stem).strip()
            if base != expected:
                findings.append(f"{r['arquivo']}: title contains '/', file name should be {expected!r}")
    # class vs counts needs word counts
    if "pct_irrecuperavel" not in columns:
        findings.append("class thresholds (R3) cannot be verified from this index: no word counts; run 'tcqa index build' on the files")
    return findings


def read_index(path: Path) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def cmd_index(args: argparse.Namespace) -> int:
    if args.action == "build":
        rows, problems = build_rows(Path(args.target))
        out = Path(args.out) if args.out else Path(args.target) / "indice.csv"
        write_index(rows, out)
        print(f"{len(rows)} row(s) written to {out}")
        for p in problems:
            print(f"  problem: {p}")
        findings = audit_index(rows)
        for f_ in findings:
            print(f"  audit: {f_}")
        return 1 if problems else 0
    rows = read_index(Path(args.target))
    findings = audit_index(rows)
    print(f"{len(rows)} row(s), {len(findings)} inconsistency(ies)")
    for f_ in findings:
        print(f"  {f_}")
    return 1 if findings else 0


def add_index_parser(sub) -> None:
    p = sub.add_parser("index", help="build the index from files, or audit an existing indice.csv")
    p.add_argument("action", choices=["build", "audit"])
    p.add_argument("target", help="folder to scan (build) or index file (audit)")
    p.add_argument("--out", help="output CSV for build (default: FOLDER/indice.csv)")
    p.set_defaults(func=cmd_index)
