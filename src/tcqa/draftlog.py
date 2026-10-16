"""``tcqa draft-log``: write the bookkeeping of a log so the reviser only judges.

Aligns raw and revised exactly like ``tcqa check`` and writes:

- the header (from the revised front matter) and bulk counts;
- one ``change`` stub for every difference the existing log does not explain,
  with ``para``, ``raw``, ``revised`` and, when the raw span repeats, ``occurrence``;
- one marker entry for every marker not yet logged.

Stubs carry ``basis: "TODO …"`` and no tier/confidence: ``tcqa check`` fails
(C0) until the reviser fills them in. A stub whose difference is a known lexicon
error is pre-filled as T1 (the checker still verifies it).
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from .checker import Checker, _span_text, sha256_bytes
from .log import Log, load_log
from .resources import load_lexicon, load_speakers
from .textnorm import find_subsequence, keys_of

TODO = "TODO"
HEADER_FIELDS = ("idioma", "falante_nativo", "derivado_de", "versao_revisao", "revisado_em", "revisado_por",
                 "classe_calculada", "classe_qualidade", "override_motivo")


def _guess_categoria(raw: str, revised: str) -> str:
    if not keys_of(raw):
        return "insercao"
    if not keys_of(revised):
        return "remocao"
    if any(w[:1].isupper() for w in revised.split()):
        return "nome"
    return "termo"


def draft(raw_text: str, revised_text: str, log: Log | None, lexicon=None, speakers=None,
          revised_name: str = "revised.md", reviser: str = "tcqa-reviser") -> list[dict]:
    raw_bytes = raw_text.encode("utf-8")
    checker = Checker(raw_text, revised_text, log, [], lexicon=lexicon, speakers=speakers, raw_bytes=raw_bytes)
    checker._align()
    checker._locate_entries()
    checker._classify_hunks()
    lines: list[dict] = []
    fm = checker.fm
    if log is None:
        header = {"type": "header", "file": revised_name, "raw_sha256": sha256_bytes(raw_bytes)}
        for key in HEADER_FIELDS:
            header[key] = fm.get(key)
        header["versao_revisao"] = header.get("versao_revisao") or 1
        header["revisado_em"] = str(header.get("revisado_em") or date.today().isoformat())
        header["revisado_por"] = header.get("revisado_por") or reviser
        header["classe_qualidade"] = header.get("classe_qualidade") or header.get("classe_calculada") or "A"
        lines.append(header)
        accent_case = sum(1 for h in checker.result.hunks if h.tag == "equal"
                          for a, b in zip(checker.raw.tokens[h.i1:h.i2], checker.rev.tokens[h.j1:h.j2]) if a.text != b.text)
        lines.append({"type": "bulk", "categoria": "pontuacao", "count": accent_case,
                      "notas": "punctuation, case, accents, paragraphs (count = words changed only in case/accent)"})
        hes = sum(1 for h in checker.result.hunks if h.status == "hesitation")
        lines.append({"type": "bulk", "categoria": "hesitacao", "count": hes, "notas": "listed fillers and immediate repetitions"})
        next_id = 1
        logged_markers: set[tuple[int, str]] = set()
    else:
        ids = [int(e["id"][1:]) for e in log.changes if str(e.get("id", "")).startswith("c") and e["id"][1:].isdigit()]
        next_id = max(ids, default=0) + 1
        logged_markers = {(e.get("para"), e.get("revised")) for e in log.changes if e.get("marker")}

    def new_id() -> str:
        nonlocal next_id
        cid = f"c{next_id:04d}"
        next_id += 1
        return cid

    raw_keys, rev_tokens = checker.raw_keys, checker.rev.tokens
    for h in checker.result.hunks:
        if h.status != "unexplained":
            continue
        raw_txt = _span_text(checker.raw.tokens, h.i1, h.i2, checker.raw.body)
        rev_txt = _span_text(rev_tokens, h.j1, h.j2, checker.rev.body)
        para = rev_tokens[min(h.j1, len(rev_tokens) - 1)].para if rev_tokens else 1
        entry = {"type": "change", "id": new_id(), "para": para, "raw": raw_txt, "revised": rev_txt,
                 "categoria": _guess_categoria(raw_txt, rev_txt), "tier": None,
                 "basis": f"{TODO}: tier (T1-T4), basis and confidence; or revert / mark", "confidence": None, "marker": None}
        rk = raw_keys[h.i1:h.i2]
        if rk:
            hits = find_subsequence(raw_keys, rk)
            if len(hits) > 1 and h.i1 in hits:
                entry["occurrence"] = hits.index(h.i1) + 1
        if lexicon is not None and lexicon.loaded and rk:
            # the aligner isolates only the differing words ('sirena' of 'ponta sirena'):
            # widen by up to 3 unchanged neighbours to find the lexicon form
            n_raw, n_rev = len(raw_keys), len(rev_tokens)
            for left in range(0, 4):
                done = False
                for right in range(0, 4):
                    a, b, c, d = h.i1 - left, h.i2 + right, h.j1 - left, h.j2 + right
                    if a < 0 or c < 0 or b > n_raw or d > n_rev:
                        continue
                    canon = lexicon.canonical_for(raw_keys[a:b])
                    if not canon:
                        continue
                    r_txt = _span_text(checker.raw.tokens, a, b, checker.raw.body)
                    v_txt = _span_text(rev_tokens, c, d, checker.rev.body)
                    if not lexicon.supports_t1(canon, r_txt, v_txt):
                        entry.update({"raw": r_txt, "revised": v_txt, "tier": "T1", "basis": f"lexicon:{canon}", "confidence": "high",
                                      "notas": "pre-filled from the lexicon; confirm the term is meant" +
                                               (" (high homophony risk)" if lexicon.is_homophone(canon) else "")})
                        entry.pop("occurrence", None)
                        hits = find_subsequence(raw_keys, raw_keys[a:b])
                        if len(hits) > 1 and a in hits:
                            entry["occurrence"] = hits.index(a) + 1
                        done = True
                        break
                if done:
                    break
        lines.append(entry)
    for m in checker.rev.markers:
        text = checker.rev.body[m.start:m.end]
        if (m.para, text) in logged_markers:
            continue
        lines.append({"type": "change", "id": new_id(), "para": m.para, "raw": m.original.strip(), "revised": text,
                      "categoria": "marcacao", "tier": None,
                      "basis": f"{TODO}: why it can't be recovered" + (" and the suggestion's reasoning" if m.suggestion else ""),
                      "confidence": "medium" if m.suggestion else None, "marker": m.kind})
    return lines


def cmd_draft_log(args: argparse.Namespace) -> int:
    raw_text = Path(args.raw).read_text(encoding="utf-8")
    revised_text = Path(args.revised).read_text(encoding="utf-8")
    log = None
    if args.log and Path(args.log).exists():
        log, _ = load_log(Path(args.log))
    lex = load_lexicon(args.lexicon) if args.lexicon else None
    sp = load_speakers(args.speakers) if args.speakers else None
    lines = draft(raw_text, revised_text, log, lex, sp, revised_name=Path(args.revised).name)
    out = Path(args.out) if args.out else (Path(args.log) if args.log else Path(args.revised).with_suffix(".log.jsonl"))
    text = "\n".join(json.dumps(x, ensure_ascii=False) for x in lines)
    if log is not None and out.exists():
        existing = out.read_text(encoding="utf-8").rstrip("\n")
        text = existing + ("\n" + text if text else "")
    out.write_text(text + "\n", encoding="utf-8", newline="\n")
    stubs = sum(1 for x in lines if str(x.get("basis", "")).startswith(TODO))
    prefilled = sum(1 for x in lines if x.get("tier") == "T1" and "pre-filled" in str(x.get("notas", "")))
    print(f"{len(lines)} line(s) written to {out}: {stubs} stub(s) to complete, {prefilled} pre-filled from the lexicon")
    return 0


def add_draft_log_parser(sub) -> None:
    p = sub.add_parser("draft-log", help="write the log skeleton (header, bulk counts, one stub per unexplained difference and marker)")
    p.add_argument("raw"); p.add_argument("revised")
    p.add_argument("--log", help="existing log: only differences it doesn't explain get stubs (appended)")
    p.add_argument("--out", help="output log (default: the --log file, or <revised>.log.jsonl)")
    p.add_argument("--lexicon"); p.add_argument("--speakers")
    p.set_defaults(func=cmd_draft_log)
