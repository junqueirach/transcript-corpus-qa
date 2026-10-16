"""``tcqa metrics``: measure a run so agent versions can be compared (evaluation set).

Per revised file, from the file and its log: words, log entries per tier, markers,
review load (items per 1,000 words), speaker naming (named vs generic labels),
main-author participation, non-content share, accepted warnings. With
``--baseline`` (a CSV written earlier) the totals are compared side by side.
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path

from .layout import log_for, revised_files
from .log import load_log, split_marker
from .resources import GENERIC_LABELS
from .textnorm import analyze

FIELDS = ["arquivo", "palavras", "entradas", "T1", "T2", "T3", "T4", "marcadores_?", "marcadores_??", "sugestoes",
          "revisao_itens", "revisao_por_mil", "rotulos_nomeados", "rotulos_genericos", "autor_principal_participa",
          "pct_irrecuperavel", "pct_nao_conteudo", "avisos_aceitos", "versao_revisao"]


def measure(path: Path, generic: set[str]) -> dict:
    doc = analyze(path.read_text(encoding="utf-8"))
    fm = doc.frontmatter or {}
    row = {k: 0 for k in FIELDS}
    row.update({"arquivo": path.name, "palavras": len(doc.tokens), "marcadores_?": doc.count_markers("?"),
                "marcadores_??": doc.count_markers("??"), "pct_irrecuperavel": fm.get("pct_irrecuperavel"),
                "pct_nao_conteudo": fm.get("pct_nao_conteudo", ""), "autor_principal_participa": fm.get("autor_principal_participa", ""),
                "versao_revisao": fm.get("versao_revisao")})
    labels = {label for _, label in doc.speakers}
    row["rotulos_genericos"] = sum(1 for label in labels if label in generic)
    row["rotulos_nomeados"] = len(labels) - row["rotulos_genericos"]
    log_path = log_for(path)
    if log_path:
        log, _ = load_log(log_path)
        if log:
            tiers = Counter(e.get("tier") for e in log.changes if e.get("marker") is None)
            row.update({t: tiers.get(t, 0) for t in ("T1", "T2", "T3", "T4")})
            row["entradas"] = len(log.changes)
            row["sugestoes"] = sum(1 for e in log.changes if e.get("marker") and (split_marker(e.get("revised", "")) or (0, 0, None))[2])
            row["revisao_itens"] = row["T3"] + row["T4"] + row["sugestoes"] + sum(1 for e in log.changes if e.get("falante_novo"))
            row["avisos_aceitos"] = len(log.accepted)
    row["revisao_por_mil"] = round(1000 * row["revisao_itens"] / row["palavras"], 2) if row["palavras"] else 0
    return row


def totals(rows: list[dict]) -> dict:
    tot = {"arquivo": "TOTAL"}
    for k in FIELDS[1:]:
        vals = [r[k] for r in rows if isinstance(r.get(k), (int, float)) and not isinstance(r.get(k), bool)]
        tot[k] = round(sum(vals), 2) if vals else ""
    tot["revisao_por_mil"] = round(1000 * tot["revisao_itens"] / tot["palavras"], 2) if tot.get("palavras") else ""
    tot["autor_principal_participa"] = sum(1 for r in rows if r.get("autor_principal_participa") is True)
    return tot


def render(rows: list[dict], baseline: list[dict] | None = None) -> str:
    cols = ["arquivo", "palavras", "entradas", "T1", "T2", "T3", "T4", "marcadores_?", "marcadores_??",
            "revisao_itens", "revisao_por_mil", "rotulos_nomeados", "rotulos_genericos", "autor_principal_participa"]
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in rows + [totals(rows)]:
        out.append("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |")
    if baseline:
        base = next((b for b in baseline if b.get("arquivo") == "TOTAL"), None)
        if base:
            now = totals(rows)
            out += ["", "**Compared with the baseline (TOTAL):**", "", "| metric | baseline | now |", "|---|---|---|"]
            for c in cols[1:]:
                out.append(f"| {c} | {base.get(c, '')} | {now.get(c, '')} |")
    return "\n".join(out) + "\n"


def cmd_metrics(args: argparse.Namespace) -> int:
    generic = set(GENERIC_LABELS) | {"Apresentador", "Entrevistador", "Participante 1", "Participante 2"}
    rows = [measure(p, generic) for p in revised_files(Path(args.target))]
    baseline = None
    if args.baseline:
        with open(args.baseline, encoding="utf-8", newline="") as f:
            baseline = list(csv.DictReader(f))
    print(render(rows, baseline))
    if args.csv:
        with open(args.csv, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
            w.writeheader()
            for r in rows + [totals(rows)]:
                w.writerow({k: r.get(k, "") for k in FIELDS})
        print(f"metrics written to {args.csv}")
    return 0


def add_metrics_parser(sub) -> None:
    p = sub.add_parser("metrics", help="measure a run (entries per tier, markers, review load, speaker naming) to compare agent versions")
    p.add_argument("target", help="revised file or folder")
    p.add_argument("--csv", help="write the metrics as CSV (use it later as --baseline)")
    p.add_argument("--baseline", help="CSV of an earlier run to compare against")
    p.set_defaults(func=cmd_metrics)
