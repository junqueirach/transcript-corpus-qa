"""``tcqa summarize``: generate the human-readable ``.correcoes.md`` summary
from a structured log. The summary is derived; the JSONL stays the source."""
from __future__ import annotations

import argparse
from pathlib import Path

from .log import Log, has_errors, load_log

CATEGORY_TITLES = {
    "nome": "Names and terms", "termo": "Names and terms", "sentido": "Meaning corrections",
    "falante": "Speaker labels", "ruido": "Noise removed", "hesitacao": "Fillers removed",
    "insercao": "Insertions", "remocao": "Removals", "traducao": "Translation", "pontuacao": "Punctuation",
}


def _cell(text) -> str:
    return " ".join(str(text if text is not None else "").split()).replace("|", "\\|")


def render_summary(log: Log) -> str:
    h = log.header
    lines = [f"# Revision log — {h.get('file', '')}", "",
             f"Revised on {h.get('revisado_em', '')} by {h.get('revisado_por', '')} · revision {h.get('versao_revisao', '')} · "
             f"language {h.get('idioma', '')} · class {h.get('classe_qualidade', '')} (computed {h.get('classe_calculada', '')})"]
    if h.get("override_motivo"):
        lines.append(f"Override reason: {h['override_motivo']}")
    if h.get("derivado_de"):
        lines.append(f"Derived from: `{h['derivado_de']}`")
    lines.append(f"Raw SHA-256: `{h.get('raw_sha256', '')}`")
    lines.append("")
    if h.get("notas"):
        lines += ["## Notes", "", str(h["notas"]), ""]

    corrections = [e for e in log.changes if e.get("marker") is None and e.get("categoria") not in ("falante",)]
    markers = [e for e in log.changes if e.get("marker") is not None]
    speakers = [e for e in log.changes if e.get("categoria") == "falante"]

    if log.bulks:
        lines += ["## Mechanical changes (bulk)", ""]
        for b in log.bulks:
            note = f" — {b['notas']}" if b.get("notas") else ""
            lines.append(f"- {b['categoria']}: {b['count']}{note}")
        lines.append("")

    if corrections:
        lines += ["## Corrections written into the text", "", "| id | ¶ | raw | revised | tier | basis |", "|---|---|---|---|---|---|"]
        for e in corrections:
            lines.append(f"| {e['id']} | {e.get('para', '')} | {_cell(e['raw'])} | {_cell(e['revised'])} | {e.get('tier') or ''} | {_cell(e.get('basis'))} |")
        lines.append("")

    if markers:
        lines += ["## Markers inserted", "", "| id | ¶ | mark | original | suggestion | conf. | reason |", "|---|---|---|---|---|---|---|"]
        for e in markers:
            from .log import split_marker
            parsed = split_marker(e["revised"]) or (e.get("marker"), e["raw"], None)
            lines.append(f"| {e['id']} | {e.get('para', '')} | `{parsed[0]}` | {_cell(parsed[1])} | {_cell(parsed[2] or '')} | {e.get('confidence') or ''} | {_cell(e.get('basis'))} |")
        lines.append("")

    lines += ["## Speakers", ""]
    if not speakers:
        lines.append("No speaker-label entries.")
    else:
        for e in speakers:
            fn = e.get("falante_novo")
            extra = f" — proposed new speaker, quote: “{fn['citacao']}”" if fn else ""
            lines.append(f"- ¶{e.get('para', '')}: {e['revised']}{extra}")
    lines.append("")

    review = [e for e in log.changes if e.get("tier") in ("T3", "T4") or e.get("confidence") in ("medium", "low")]
    lines += ["## To review (T3, T4 and suggestions)", ""]
    if not review:
        lines.append("Nothing.")
    else:
        for e in review:
            lines.append(f"- {e['id']} ¶{e.get('para', '')} [{e.get('tier') or 'marker'}/{e.get('confidence') or '-'}]: {_cell(e['raw'])} → {_cell(e['revised'])}")
    lines.append("")
    return "\n".join(lines)


def cmd_summarize(args: argparse.Namespace) -> int:
    log, issues = load_log(Path(args.log))
    if log is None or has_errors(issues):
        for i in issues:
            print(i)
        print("log is invalid; fix it before summarising")
        return 1
    text = render_summary(log)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"summary written to {args.out}")
    else:
        print(text)
    return 0


def add_summarize_parser(sub) -> None:
    p = sub.add_parser("summarize", help="generate the human-readable summary (.correcoes.md) from a JSONL log")
    p.add_argument("log")
    p.add_argument("--out", help="write to this file instead of printing")
    p.set_defaults(func=cmd_summarize)
