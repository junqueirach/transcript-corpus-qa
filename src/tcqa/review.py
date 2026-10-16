"""``tcqa review``: one human review queue for a whole run, and applying the decisions.

``build`` scans every log under a folder and groups what a person must look at:
T3/T4 corrections, suggestions (``⟶ sugestão:``), new speakers, high-homophony
lexicon fixes. Identical items across files become one row (one decision).
Pre-approved entities (``--approved``) are left out.

``apply`` reads the queue JSON after the reviewer filled ``decisao``
(``aprovar`` / ``rejeitar``) and changes the files:

- suggestion approved → the marker is replaced by the suggestion in the revised
  text; the log entry becomes a correction (tier from the row, default T2);
- correction (T3/T4) rejected → the text goes back to a marker with the
  correction as a suggestion;
- new speaker approved → added to the registry (backup kept); approved T4 names
  are added to the pre-approved entities file.

Every changed file gets ``versao_revisao`` + 1. Afterwards run
``tcqa classify --write`` and ``tcqa check`` again.
"""
from __future__ import annotations

import argparse
import json
import shutil
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

from .frontmatter import join_document, split_document
from .layout import logs_in, revised_for_log
from .log import ARROW, load_log, split_marker
from .textnorm import keys_of

DECISIONS = ("aprovar", "rejeitar")


def _approved_set(path: Path | None) -> set[tuple[str, ...]]:
    if not path or not path.exists():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    return {tuple(keys_of(x)) for x in data.get("entidades", [])}


def _item(entry: dict) -> tuple[str, str, str] | None:
    """(kind, raw, proposed) of a log entry that needs a human, or None."""
    marker, tier, conf = entry.get("marker"), entry.get("tier"), entry.get("confidence")
    if entry.get("falante_novo"):
        return "falante_novo", entry["falante_novo"].get("citacao", ""), entry["falante_novo"].get("nome", "")
    if marker:
        parsed = split_marker(entry.get("revised", ""))
        if parsed and parsed[2]:
            return "sugestao", parsed[1], parsed[2]
        return None
    if tier in ("T3", "T4"):
        return f"correcao_{tier}", entry.get("raw", ""), entry.get("revised", "")
    return None


def _core(raw: str, proposed: str) -> tuple[str, str]:
    """Drop the context words both sides share at their ends ('Dick Chen era' →
    'Dick Cheney era' becomes 'Chen' → 'Cheney'), so repeats group together."""
    rw, pw = raw.split(), proposed.split()
    key = lambda w: tuple(keys_of(w))
    while len(rw) > 1 and len(pw) > 1 and key(rw[0]) == key(pw[0]):
        rw, pw = rw[1:], pw[1:]
    while len(rw) > 1 and len(pw) > 1 and key(rw[-1]) == key(pw[-1]):
        rw, pw = rw[:-1], pw[:-1]
    return " ".join(rw), " ".join(pw).strip(".,;:!?")


BATCHES = ("falantes", "correcoes_verificadas", "correcoes", "sugestoes_nomes", "sugestoes", "palavras_cortadas")
BATCH_TITLES = {
    "falantes": "New speakers",
    "correcoes_verificadas": "Corrections from outside knowledge, confirmed by the verifier (low risk: approve as a batch?)",
    "correcoes": "Corrections from outside knowledge or another file",
    "sugestoes_nomes": "Suggestions: names",
    "sugestoes": "Suggestions: words and phrases",
    "palavras_cortadas": "Suggestions: cut-off words completed (low risk: approve or reject as a batch)",
}


def _batch(g: dict) -> str:
    if g["tipo"] == "falante_novo":
        return "falantes"
    if g["tipo"].startswith("correcao"):
        return "correcoes_verificadas" if g.get("verificado") else "correcoes"
    raw, prop = keys_of(g["raw"]), keys_of(g["proposto"])
    if len(raw) == 1 and len(prop) == 1 and len(raw[0]) >= 2 and prop[0].startswith(raw[0]) and prop[0] != raw[0]:
        return "palavras_cortadas"
    if any(w[:1].isupper() for w in g["proposto"].split()):
        return "sugestoes_nomes"
    return "sugestoes"


def build_queue(target: Path, approved: Path | None = None) -> dict:
    skip = _approved_set(approved)
    groups: dict[tuple, dict] = {}
    for log_path in logs_in(target):
        log, _ = load_log(log_path)
        if log is None:
            continue
        rev = revised_for_log(log_path)
        for e in log.changes:
            item = _item(e)
            if item is None:
                continue
            kind, raw, proposed = item
            if kind != "falante_novo":
                raw, proposed = _core(raw, proposed)
            if kind.startswith("correcao") and tuple(keys_of(proposed)) in skip:
                continue
            # corrections to the same name are one decision whatever the raw form ('El', 'Elan' → Elon)
            raw_key = () if kind.startswith("correcao") else tuple(keys_of(raw))
            key = (kind, raw_key, " ".join(proposed.split()).casefold())
            if key in groups and kind.startswith("correcao"):
                forms = groups[key]["raw"].split(" / ")
                if " ".join(raw.split()) not in forms:
                    groups[key]["raw"] = " / ".join(forms + [" ".join(raw.split())])
            g = groups.setdefault(key, {"n": 0, "tipo": kind, "raw": " ".join(raw.split()), "proposto": " ".join(proposed.split()),
                                        "tier_sugerido": "T2" if kind == "sugestao" else e.get("tier"),
                                        "basis": e.get("basis"), "decisao": None, "ocorrencias": []})
            verified = "verificado" in str(e.get("notas") or "").casefold()
            g["verificado"] = verified if not g["ocorrencias"] else (g["verificado"] and verified)
            g["ocorrencias"].append({"log": str(log_path), "revisado": str(rev) if rev else None,
                                     "id": e.get("id"), "para": e.get("para")})
    for g in groups.values():
        g["lote"] = _batch(g)
    order = {b: i for i, b in enumerate(BATCHES)}
    rows = sorted(groups.values(), key=lambda g: (order[g["lote"]], g["tipo"], -len(g["ocorrencias"]), g["proposto"]))
    for i, g in enumerate(rows, 1):
        g["n"] = i
    return {"_uso": "Preencha 'decisao' com 'aprovar' ou 'rejeitar' (null = decidir depois). "
                    "Em sugestões aprovadas pode mudar 'tier_sugerido' (T2/T3/T4). Depois: tcqa review apply <este arquivo>.",
            "gerado_em": datetime.now().isoformat(timespec="seconds"), "itens": rows}


def render_queue(queue: dict) -> str:
    rows = queue["itens"]
    out = ["# Human review queue", "", f"{len(rows)} item(s) to decide, "
           f"{sum(len(r['ocorrencias']) for r in rows)} occurrence(s). Fill `decisao` in the JSON file "
           "(`aprovar` / `rejeitar`; a whole batch can be decided at once with `tcqa review decide QUEUE --lote <name> --decisao aprovar`), "
           "then run `tcqa review apply`.", ""]
    out += ["| batch | items |", "|---|---|"] + [f"| {BATCH_TITLES[b]} (`{b}`) | {sum(1 for r in rows if r.get('lote') == b)} |"
                                               for b in BATCHES if any(r.get("lote") == b for r in rows)] + [""]
    cell = lambda s, n=90: (s or "").replace("|", "\\|")[:n]
    for b in BATCHES:
        items = [r for r in rows if r.get("lote") == b]
        if not items:
            continue
        out += [f"## {BATCH_TITLES[b]}", "", "| # | type | raw → proposed | × | files | basis |", "|---|---|---|---|---|---|"]
        for r in items:
            files = sorted({Path(o["log"]).name.replace(".log.jsonl", "") for o in r["ocorrencias"]})
            out.append(f"| {r['n']} | {r['tipo']} | {cell(r['raw'], 60)} → **{cell(r['proposto'], 60)}** | {len(r['ocorrencias'])} | "
                       f"{cell('; '.join(files), 80)} | {cell(r.get('basis'))} |")
        out.append("")
    return "\n".join(out) + "\n"


def decide_batch(queue: dict, batch: str, decision: str, only_undecided: bool = True) -> int:
    n = 0
    for r in queue["itens"]:
        if r.get("lote") == batch and (r.get("decisao") is None or not only_undecided):
            r["decisao"] = decision
            n += 1
    return n


# ------------------------------------------------------------------ apply

def _bump(fm: dict, header: dict, today: str, by: str) -> None:
    for d in (fm, header):
        d["versao_revisao"] = int(d.get("versao_revisao") or 1) + 1
        d["revisado_em"] = today
    header["revisado_por"] = by


def _replace_in_para(body: str, para: int | None, old: str, new: str) -> str | None:
    """Replace ``old`` by ``new`` once, preferring the given paragraph."""
    blocks = body.split("\n\n")
    text_idx = [i for i, b in enumerate(blocks) if b.strip() and not b.strip().startswith(">")]
    order = []
    if para and 1 <= para <= len(text_idx):
        order.append(text_idx[para - 1])
    order += [i for i in range(len(blocks)) if i not in order]
    for i in order:
        if old in blocks[i]:
            blocks[i] = blocks[i].replace(old, new, 1)
            return "\n\n".join(blocks)
    return None


def apply_queue(queue: dict, by: str = "revisor humano", speakers: Path | None = None,
                approved: Path | None = None) -> list[str]:
    today = date.today().isoformat()
    report: list[str] = []
    per_log: dict[str, list[tuple[dict, dict]]] = defaultdict(list)
    for row in queue["itens"]:
        if row.get("decisao") not in DECISIONS:
            continue
        for occ in row["ocorrencias"]:
            per_log[occ["log"]].append((row, occ))
    new_speakers, new_entities = set(), set()
    for log_name, items in per_log.items():
        log_path = Path(log_name)
        lines = [json.loads(x) for x in log_path.read_text(encoding="utf-8").splitlines() if x.strip()]
        by_id = {l.get("id"): l for l in lines if l.get("type") == "change"}
        rev_path = revised_for_log(log_path)
        if rev_path is None:
            report.append(f"{log_path.name}: revised file not found, skipped")
            continue
        fm, body, _ = split_document(rev_path.read_text(encoding="utf-8"))
        fm = dict(fm or {})
        changed = False
        for row, occ in items:
            e = by_id.get(occ["id"])
            if e is None:
                report.append(f"{log_path.name} {occ['id']}: entry not found")
                continue
            decision, kind = row["decisao"], row["tipo"]
            if kind == "sugestao" and decision == "aprovar":
                parsed = split_marker(e["revised"])
                if not parsed:
                    continue
                tier = row.get("tier_sugerido") or "T2"
                new_body = _replace_in_para(body, e.get("para"), e["revised"], parsed[2])
                if new_body is None:
                    report.append(f"{rev_path.name} {e['id']}: marker text not found, skipped")
                    continue
                body = new_body
                prefix = {"T2": "context:", "T3": "crossfile:", "T4": "external:"}.get(tier, "")
                e.update({"revised": parsed[2], "marker": None, "tier": tier, "confidence": "high",
                          "basis": f"{prefix} approved by {by} {today}; {e.get('basis') or ''}".strip(),
                          "categoria": e["categoria"] if e.get("categoria") != "marcacao" else ("nome" if parsed[2][:1].isupper() else "termo")})
                if tier == "T4":
                    new_entities.add(parsed[2])
                changed = True
                report.append(f"{rev_path.name} {e['id']}: suggestion applied → '{parsed[2]}' ({tier})")
            elif kind.startswith("correcao") and decision == "rejeitar":
                marker_text = f"[[? {e['raw']} {ARROW} sugestão: {e['revised']} ]]"
                new_body = _replace_in_para(body, e.get("para"), e["revised"], marker_text)
                if new_body is None:
                    report.append(f"{rev_path.name} {e['id']}: corrected text not found, skipped")
                    continue
                body = new_body
                e.update({"revised": marker_text, "marker": "?", "tier": None, "confidence": "medium", "categoria": "marcacao",
                          "basis": f"correction rejected by {by} {today}; was: {e.get('basis') or ''}"})
                changed = True
                report.append(f"{rev_path.name} {e['id']}: correction rejected → marker")
            elif kind.startswith("correcao") and decision == "aprovar":
                e["notas"] = f"approved by {by} {today}"
                if e.get("tier") == "T4":
                    new_entities.add(e["revised"])
                changed = True
            elif kind == "sugestao" and decision == "rejeitar":
                e["notas"] = f"suggestion rejected by {by} {today}"
                changed = True
            elif kind == "falante_novo" and decision == "aprovar":
                new_speakers.add(e["falante_novo"]["nome"])
                e["notas"] = f"speaker approved by {by} {today}"
                changed = True
        if changed:
            header = lines[0]
            _bump(fm, header, today, by)
            rev_path.write_text(join_document(fm, body), encoding="utf-8", newline="\n")
            log_path.write_text("\n".join(json.dumps(l, ensure_ascii=False) for l in lines) + "\n", encoding="utf-8", newline="\n")
            report.append(f"{rev_path.name}: versao_revisao → {fm['versao_revisao']} (run classify --write and check)")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if new_speakers and speakers and speakers.exists():
        shutil.copy2(speakers, speakers.with_name(f"{speakers.stem}.backup-{stamp}{speakers.suffix}"))
        data = json.loads(speakers.read_text(encoding="utf-8"))
        data.setdefault("falantes", [])
        for name in sorted(new_speakers):
            if name not in data["falantes"]:
                data["falantes"].append(name)
        speakers.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        report.append(f"registry: {len(new_speakers)} speaker(s) approved → {speakers.name}")
    if new_entities and approved:
        data = json.loads(approved.read_text(encoding="utf-8")) if approved.exists() else {
            "_uso": "Entidades públicas já aprovadas por um humano: correções T4 para elas não voltam à fila de revisão.", "entidades": []}
        for name in sorted(new_entities):
            if name not in data["entidades"]:
                data["entidades"].append(name)
        approved.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
        report.append(f"pre-approved entities: +{len(new_entities)} → {approved.name}")
    return report


def cmd_review(args: argparse.Namespace) -> int:
    approved = Path(args.approved) if args.approved else None
    if args.action == "build":
        queue = build_queue(Path(args.target), approved)
        out_json = Path(args.json or (Path(args.target) / "revisao_humana.json" if Path(args.target).is_dir() else "revisao_humana.json"))
        out_json.write_text(json.dumps(queue, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
        md = render_queue(queue)
        out_md = Path(args.out) if args.out else out_json.with_suffix(".md")
        out_md.write_text(md, encoding="utf-8", newline="\n")
        print(f"{len(queue['itens'])} item(s) → {out_md} and {out_json}")
        return 0
    queue = json.loads(Path(args.target).read_text(encoding="utf-8"))
    if args.action == "decide":
        if args.lote not in BATCHES or args.decisao not in DECISIONS:
            print(f"use --lote one of {list(BATCHES)} and --decisao one of {list(DECISIONS)}")
            return 1
        n = decide_batch(queue, args.lote, args.decisao)
        Path(args.target).write_text(json.dumps(queue, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
        Path(args.target).with_suffix(".md").write_text(render_queue(queue), encoding="utf-8", newline="\n")
        print(f"{n} item(s) in '{args.lote}' set to {args.decisao}")
        return 0
    for line in apply_queue(queue, by=args.by, speakers=Path(args.speakers) if args.speakers else None, approved=approved):
        print(f"  {line}")
    return 0


def add_review_parser(sub) -> None:
    p = sub.add_parser("review", help="build one grouped human review queue for a folder, or apply its decisions")
    p.add_argument("action", choices=["build", "decide", "apply"])
    p.add_argument("target", help="build: folder (or log) · decide/apply: the queue JSON")
    p.add_argument("--lote", help="decide: the batch to decide at once (e.g. palavras_cortadas, correcoes_verificadas)")
    p.add_argument("--decisao", help="decide: aprovar or rejeitar")
    p.add_argument("--out", help="build: Markdown queue (default: next to the JSON)")
    p.add_argument("--json", help="build: queue JSON (default: <folder>/revisao_humana.json)")
    p.add_argument("--approved", help="pre-approved public entities JSON (left out of the queue; apply adds approved T4 names)")
    p.add_argument("--speakers", help="apply: speaker registry to add approved new speakers to")
    p.add_argument("--by", default="revisor humano", help="apply: who decided (written in the log)")
    p.set_defaults(func=cmd_review)
