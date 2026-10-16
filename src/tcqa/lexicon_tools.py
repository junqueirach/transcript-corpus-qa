"""``tcqa lexicon``: validate, inspect, merge and grow a lexicon.

- ``hits``: the lexicon entries that occur in one raw file (with near-matches), so a
  reviser reads 20 relevant entries instead of 800.
- ``validate`` / ``stats``: structural problems and counts.
- ``merge``: union of several lexicons by term.
- ``learn``: grow the lexicon from finished logs (decision B5). New ASR forms of
  terms already in the lexicon are added automatically when seen at least ``--min``
  times (never for high-homophony terms); new terms only go to a pending file for
  human approval. Every write keeps a dated backup and a changelog line.
"""
from __future__ import annotations

import argparse
import difflib
import json
import shutil
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from .language import STOPWORDS
from .log import load_log
from .resources import load_lexicon, load_speakers, merge_speaker_names
from .textnorm import analyze, keys_of

HOMOPHONE_VALUES = ("alto", "high")
# common words (keys, accent-free): stop words of every language plus frequent
# Portuguese words a lexicon error form must not be without a homophony flag
COMMON_WORDS = set().union(*STOPWORDS.values()) | {
    "da", "dá", "pra", "antes", "vale", "obra", "obras", "vida", "mesmo", "caos", "deus", "luz", "mente", "mental",
    "era", "eras", "lei", "fogo", "agua", "terra", "mar", "sol", "anjo", "ceu", "alma", "amor", "paz", "dan", "ana",
    "ser", "seres", "nos", "voz", "tempo", "mundo", "casa", "porta", "grupo", "forma", "nome", "ponto", "verbo",
}
COMMON_WORDS = {k for w in COMMON_WORDS for k in keys_of(w)}


def _terms(data: dict) -> list[dict]:
    return data.get("termos") or data.get("terms") or []


def _read_json(path: Path) -> tuple[dict, int]:
    """The JSON and the indent it was written with (to keep the user's format)."""
    text = path.read_text(encoding="utf-8")
    indent = 2
    for line in text.splitlines()[1:]:
        if line.strip():
            indent = len(line) - len(line.lstrip(" ")) or 2
            break
    return json.loads(text), indent


def _write_json(path: Path, data: dict, indent: int) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=indent) + "\n", encoding="utf-8", newline="\n")


def _forms(entry: dict) -> list[tuple[str, str]]:
    out = [("termo", entry.get("termo") or entry.get("term") or "")]
    out += [("variante", v) for v in entry.get("variantes") or entry.get("variants") or []]
    out += [("erro", e) for e in entry.get("erros_previstos") or entry.get("expected_errors") or []]
    out += [("erro", e) for e in entry.get("erros_observados") or entry.get("observed_errors") or []]
    return [(k, f) for k, f in out if f]


# ------------------------------------------------------------------ hits

def lexicon_hits(raw_text: str, data: dict, fuzzy: float = 0.86, context: int = 6) -> dict:
    doc = analyze(raw_text)
    keys = [t.key for t in doc.tokens]
    words = [t.text for t in doc.tokens]
    by_first: dict[str, list[tuple[tuple[str, ...], dict, str, str]]] = defaultdict(list)
    single_forms: dict[str, dict] = {}
    for entry in _terms(data):
        for kind, form in _forms(entry):
            fk = tuple(keys_of(form))
            if fk:
                by_first[fk[0]].append((fk, entry, kind, form))
                if len(fk) == 1 and len(fk[0]) >= 5:
                    single_forms.setdefault(fk[0], entry)
    found: dict[str, dict] = {}
    for i, k in enumerate(keys):
        counted: set[str] = set()
        # longest form first, and each term at most once per position
        for fk, entry, kind, form in sorted(by_first.get(k, ()), key=lambda x: (-len(x[0]), x[2] != "termo")):
            if tuple(keys[i:i + len(fk)]) != fk:
                continue
            term = entry.get("termo") or entry.get("term")
            if term in counted:
                continue
            counted.add(term)
            rec = found.setdefault(term, {"termo": term, "cat": entry.get("cat"),
                                          "risco_homofonia": entry.get("risco_homofonia"),
                                          "variantes": entry.get("variantes") or [],
                                          "gloss": (entry.get("gloss") or "")[:160] or None,
                                          "encontrado_como": Counter(), "exemplos": []})
            rec["encontrado_como"][f"{kind}: {' '.join(words[i:i + len(fk)])}"] += 1
            if kind == "erro" and len(fk) == 1 and fk[0] in COMMON_WORDS:
                rec["forma_e_palavra_comum"] = True
            if len(rec["exemplos"]) < 2:
                rec["exemplos"].append(" ".join(words[max(0, i - context):i + len(fk) + context]))
    # near-matches: long words close to a lexicon form but not listed (candidate new ASR errors)
    near: dict[str, dict] = {}
    known = set(single_forms)
    for i, k in enumerate(keys):
        if len(k) < 5 or k in known or k in COMMON_WORDS or not (words[i][:1].isupper() or len(k) >= 8):
            continue
        match = difflib.get_close_matches(k, known, n=1, cutoff=fuzzy)
        if match:
            entry = single_forms[match[0]]
            term = entry.get("termo") or entry.get("term")
            rec = near.setdefault(f"{words[i]} ~ {term}", {"palavra": words[i], "termo": term, "vezes": 0,
                                                           "risco_homofonia": entry.get("risco_homofonia"),
                                                           "exemplo": " ".join(words[max(0, i - context):i + 1 + context])})
            rec["vezes"] += 1
    # entries matched only through a common word go last: they are the likeliest false hits
    hits = sorted(found.values(), key=lambda r: (bool(r.get("forma_e_palavra_comum")) or
                                                 str(r.get("risco_homofonia") or "").casefold() in HOMOPHONE_VALUES,
                                                 -sum(r["encontrado_como"].values())))
    for r in hits:
        r["encontrado_como"] = dict(r["encontrado_como"])
    return {"palavras": len(keys), "termos_encontrados": len(hits), "hits": hits,
            "quase": sorted(near.values(), key=lambda r: -r["vezes"])}


# ------------------------------------------------------------------ validate / stats / merge

def validate(data: dict) -> list[str]:
    problems: list[str] = []
    terms = _terms(data)
    if not isinstance(terms, list) or not terms:
        return ["no 'termos' list"]
    owner: dict[tuple, str] = {}
    for n, entry in enumerate(terms, 1):
        term = entry.get("termo") or entry.get("term")
        if not term:
            problems.append(f"entry {n}: no 'termo'")
            continue
        tk = tuple(keys_of(term))
        if tk in owner:
            problems.append(f"'{term}': duplicate term (same as '{owner[tk]}')")
        owner.setdefault(tk, term)
    for entry in terms:
        term = entry.get("termo") or entry.get("term")
        for kind, form in _forms(entry):
            fk = tuple(keys_of(form))
            if kind == "erro" and fk in owner and owner[fk] != term:
                problems.append(f"'{term}': error form '{form}' is another term ('{owner[fk]}'); a T1 fix would be ambiguous")
            homophone = str(entry.get("risco_homofonia") or "").casefold() in HOMOPHONE_VALUES
            if kind == "erro" and len(fk) == 1 and fk[0] in COMMON_WORDS and not homophone:
                problems.append(f"'{term}': error form '{form}' is a common word; set risco_homofonia: alto or remove the form")
    return problems


def corpus_common_forms(data: dict, raw_paths: list[Path], share: float = 0.5) -> list[str]:
    """Error forms that occur in at least ``share`` of the raw files: in a real corpus an
    ASR error of a rare term is rare, so a form found nearly everywhere is a common word."""
    forms: dict[tuple, list[str]] = {}
    for entry in _terms(data):
        if str(entry.get("risco_homofonia") or "").casefold() in HOMOPHONE_VALUES:
            continue
        term = entry.get("termo") or entry.get("term")
        for kind, form in _forms(entry):
            if kind == "erro":
                fk = tuple(keys_of(form))
                if fk:
                    forms.setdefault(fk, []).append(f"'{term}': error form '{form}'")
    counts: Counter = Counter()
    n = 0
    for path in raw_paths:
        try:
            keys = [t.key for t in analyze(path.read_text(encoding="utf-8")).tokens]
        except (OSError, UnicodeDecodeError):
            continue
        n += 1
        seen = set()
        for i in range(len(keys)):
            for size in (1, 2, 3):
                k = tuple(keys[i:i + size])
                if k in forms:
                    seen.add(k)
        counts.update(seen)
    if not n:
        return []
    out = []
    for fk, labels in forms.items():
        if counts[fk] / n >= share:
            for label in labels:
                out.append(f"{label} occurs in {counts[fk]}/{n} raw files: possibly a common word (set risco_homofonia: alto or remove it)")
    return out


def stats(data: dict) -> dict:
    terms = _terms(data)
    return {"termos": len(terms),
            "por_categoria": dict(Counter(e.get("cat") or "?" for e in terms).most_common()),
            "risco_homofonia_alto": sum(1 for e in terms if str(e.get("risco_homofonia") or "").casefold() in HOMOPHONE_VALUES),
            "com_erros_observados": sum(1 for e in terms if e.get("erros_observados")),
            "sem_erros_previstos": sum(1 for e in terms if not (e.get("erros_previstos") or e.get("erros_observados")))}


def merge(datasets: list[dict]) -> dict:
    out: dict[tuple, dict] = {}
    for data in datasets:
        for entry in _terms(data):
            term = entry.get("termo") or entry.get("term")
            if not term:
                continue
            tk = tuple(keys_of(term))
            if tk not in out:
                out[tk] = json.loads(json.dumps(entry, ensure_ascii=False))
                continue
            cur = out[tk]
            for field in ("variantes", "erros_previstos", "erros_observados"):
                merged = list(dict.fromkeys((cur.get(field) or []) + (entry.get(field) or [])))
                if merged:
                    cur[field] = merged
            for k, v in entry.items():
                cur.setdefault(k, v)
    base = dict(datasets[0]) if datasets else {}
    base["termos"] = list(out.values())
    if "_total" in base:
        base["_total"] = len(base["termos"])
    return base


# ------------------------------------------------------------------ learn (B5)

def _core(lex, revised: str, raw: str):
    """(term, raw form) when the revised span writes a lexicon term and the raw span
    replaced at that place is not yet a listed form of it."""
    rk, vk = tuple(keys_of(raw)), tuple(keys_of(revised))
    # already known: some term writes exactly this revised span and lists this raw span
    for tk, forms in lex.written.items():
        if vk in forms and rk in lex.replaceable[tk]:
            return None
    candidates = []
    for tk, forms in lex.written.items():
        for form in forms:
            if len(form) == 1 and (form[0] in COMMON_WORDS or len(form[0]) <= 3):
                continue                       # a match through a common word ('pra' of PRA) proves nothing
            n = len(form)
            for i in range(len(vk) - n + 1):
                if vk[i:i + n] != form:
                    continue
                pre, post = vk[:i], vk[i + n:]
                if len(rk) > len(pre) + len(post) and rk[:len(pre)] == pre and rk[len(rk) - len(post):] == post:
                    core = rk[len(pre):len(rk) - len(post)]
                    if core and core not in lex.replaceable[tk] and core != tk:
                        candidates.append((n, lex.canonical[tk], core))
    if not candidates:
        return None
    _, term, core = max(candidates, key=lambda c: c[0])   # the longest term wins ('Rui Sol Andrade' over 'Sol Andrade')
    return term, core


def learn(log_paths: list[Path], lexicon_path: Path, speakers_path: Path | None, min_count: int) -> dict:
    lex = load_lexicon(lexicon_path)
    if speakers_path:
        merge_speaker_names(lex, load_speakers(speakers_path))
    observed: dict[tuple[str, tuple], dict] = {}
    pending: dict[str, dict] = {}
    for path in log_paths:
        log, _ = load_log(path)
        if log is None:
            continue
        for e in log.changes:
            if e.get("marker") is not None or e.get("confidence") != "high" or e.get("tier") not in ("T1", "T2", "T3", "T4"):
                continue
            hit = _core(lex, e.get("revised", ""), e.get("raw", ""))
            if hit:
                term, core = hit
                raw_words = " ".join(e["raw"].split())
                rec = observed.setdefault((term, core), {"termo": term, "forma": " ".join(core), "vezes": 0, "arquivos": set(), "exemplo": raw_words})
                rec["vezes"] += 1
                rec["arquivos"].add(path.name)
                continue
            # a capitalised name written into the text that the lexicon doesn't know: a pending term
            if e.get("categoria") in ("nome", "termo") and e.get("tier") in ("T2", "T3", "T4"):
                # only the changed core (context words shared at both ends dropped), only real names
                rw, pw = e.get("raw", "").split(), e.get("revised", "").split()
                while len(rw) > 1 and len(pw) > 1 and keys_of(rw[0]) == keys_of(pw[0]):
                    rw, pw = rw[1:], pw[1:]
                while len(rw) > 1 and len(pw) > 1 and keys_of(rw[-1]) == keys_of(pw[-1]):
                    rw, pw = rw[:-1], pw[:-1]
                new_words = [w.strip(".,;:!?()\"'") for w in pw if w[:1].isupper()]
                new_words = [w for w in new_words if len(w) >= 3 and not set(keys_of(w)) <= COMMON_WORDS]
                if new_words and not any(tuple(keys_of(w)) in lex.canonical for w in new_words):
                    name = " ".join(new_words)
                    rec = pending.setdefault(name, {"termo": name, "formas_asr": Counter(), "vezes": 0, "arquivos": set(), "tiers": Counter(), "basis": []})
                    rec["formas_asr"][" ".join(rw)] += 1
                    rec["vezes"] += 1
                    rec["arquivos"].add(path.name)
                    rec["tiers"][e.get("tier")] += 1
                    if len(rec["basis"]) < 2:
                        rec["basis"].append(e.get("basis", ""))
    auto, held = [], []
    for rec in observed.values():
        rec["arquivos"] = sorted(rec["arquivos"])
        enough = rec["vezes"] >= min_count or len(rec["arquivos"]) >= 2
        homophone = lex.is_homophone(rec["termo"])
        common = set(keys_of(rec["forma"])) <= COMMON_WORDS      # 'mental' for Mentalma: a real word, never automatic
        if enough and not homophone and not common:
            auto.append({**rec, "motivo": None})
        else:
            why = ("risco de homofonia: precisa aprovação" if homophone else
                   "forma é palavra comum: precisa aprovação (e risco_homofonia no termo)" if common else
                   f"visto {rec['vezes']}× (< {min_count})")
            held.append({**rec, "motivo": why})
    pend = []
    for rec in pending.values():
        pend.append({**rec, "formas_asr": dict(rec["formas_asr"]), "arquivos": sorted(rec["arquivos"]), "tiers": dict(rec["tiers"])})
    return {"automatico": auto, "retido": held, "pendente": sorted(pend, key=lambda r: -r["vezes"])}


def apply_learning(lexicon_path: Path, result: dict, pending_path: Path | None, changelog: Path | None, run_label: str) -> str:
    data, indent = _read_json(lexicon_path)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = lexicon_path.with_name(f"{lexicon_path.stem}.backup-{stamp}{lexicon_path.suffix}")
    shutil.copy2(lexicon_path, backup)
    by_key = {tuple(keys_of(e.get("termo") or "")): e for e in _terms(data)}
    added = []
    for rec in result["automatico"]:
        entry = by_key.get(tuple(keys_of(rec["termo"])))
        if entry is None:      # a registry speaker name, not a lexicon term: create the entry
            entry = {"termo": rec["termo"], "cat": "ENTIDADE", "variantes": [], "erros_previstos": [], "n_obras": 0,
                     "_origem": f"tcqa lexicon learn {stamp}"}
            data.setdefault("termos", []).append(entry)
            by_key[tuple(keys_of(rec["termo"]))] = entry
        for field in ("erros_observados", "erros_previstos"):
            entry.setdefault(field, [])
            if rec["forma"] not in entry[field]:
                entry[field].append(rec["forma"])
        added.append(f"{rec['termo']} ← {rec['forma']} ({rec['vezes']}×)")
    if "_total" in data:
        data["_total"] = len(_terms(data))
    _write_json(lexicon_path, data, indent)
    load_lexicon(lexicon_path)   # must still load
    if pending_path is not None and result["pendente"]:
        old = json.loads(pending_path.read_text(encoding="utf-8")) if pending_path.exists() else {"termos": []}
        known = {p["termo"]: p for p in old.get("termos", [])}
        for rec in result["pendente"]:
            cur = known.get(rec["termo"])
            if cur:
                cur["vezes"] = cur.get("vezes", 0) + rec["vezes"]
                cur["arquivos"] = sorted(set(cur.get("arquivos", [])) | set(rec["arquivos"]))
                for f, n in rec["formas_asr"].items():
                    cur.setdefault("formas_asr", {})[f] = cur["formas_asr"].get(f, 0) + n
            else:
                known[rec["termo"]] = {**rec, "status": "pendente", "_origem": run_label}
        old["termos"] = sorted(known.values(), key=lambda r: -r.get("vezes", 0))
        old["_uso"] = "Termos candidatos ainda NÃO aprovados. O revisor só pode usá-los como pista para T2, nunca como base T1. Aprovar = mover para o léxico."
        pending_path.write_text(json.dumps(old, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    if changelog is not None:
        lines = [f"\n## {datetime.now():%Y-%m-%d %H:%M} — {run_label}\n",
                 f"- backup: `{backup.name}`\n",
                 f"- added automatically ({len(added)}): " + ("; ".join(added) if added else "none") + "\n",
                 f"- held for approval: {len(result['retido'])}; pending new terms: {len(result['pendente'])}\n"]
        new_file = not changelog.exists() or changelog.stat().st_size == 0
        with open(changelog, "a", encoding="utf-8", newline="\n") as f:
            if new_file:
                f.write("# Lexicon changelog\n")
            f.writelines(lines)
    return backup.name


# ------------------------------------------------------------------ CLI

def cmd_lexicon(args: argparse.Namespace) -> int:
    if args.action == "hits":
        data, _ = _read_json(Path(args.lexicon))
        if args.speakers:
            sp = json.loads(Path(args.speakers).read_text(encoding="utf-8"))
            extra = []
            author = sp.get("autor_principal") or {}
            if author.get("nome_canonico"):
                extra.append({"termo": author["nome_canonico"], "cat": "FALANTE", "erros_previstos": author.get("variantes_de_transcricao") or []})
            for ch in sp.get("canais") or []:
                for p in ch.get("falantes_conhecidos") or []:
                    if p.get("nome"):
                        extra.append({"termo": p["nome"], "cat": "FALANTE", "erros_previstos": p.get("variantes_de_transcricao") or []})
            data = merge([data, {"termos": extra}])
        result = lexicon_hits(Path(args.target).read_text(encoding="utf-8"), data, fuzzy=args.fuzzy)
        text = json.dumps(result, ensure_ascii=False, indent=1)
        if args.out:
            Path(args.out).write_text(text + "\n", encoding="utf-8", newline="\n")
            print(f"{result['termos_encontrados']} term(s) found, {len(result['quase'])} near-match(es) → {args.out}")
        else:
            print(text)
        return 0
    if args.action == "validate":
        data, _ = _read_json(Path(args.target))
        problems = validate(data)
        for p in problems:
            print(f"  {p}")
        if args.corpus:
            raws = [p for p in sorted(Path(args.corpus).rglob("*.md"))
                    if not any(part.startswith("_") for part in p.relative_to(Path(args.corpus)).parts[:-1])
                    and not p.read_text(encoding="utf-8", errors="replace").startswith("---")]
            advice = corpus_common_forms(data, raws, args.common_share)
            print(f"advice ({len(advice)}): error forms frequent in the corpus — check each, it may be a common word")
            for a in advice:
                print(f"  ? {a}")
        print(f"{'INVALID' if problems else 'VALID'} — {len(_terms(data))} term(s), {len(problems)} problem(s)")
        load_lexicon(Path(args.target))
        return 1 if problems else 0
    if args.action == "stats":
        data, _ = _read_json(Path(args.target))
        print(json.dumps(stats(data), ensure_ascii=False, indent=1))
        return 0
    if args.action == "merge":
        datasets = [_read_json(Path(p))[0] for p in [args.target] + (args.others or [])]
        merged = merge(datasets)
        out = Path(args.out or "lexicon.merged.json")
        _write_json(out, merged, _read_json(Path(args.target))[1])
        print(f"{len(_terms(merged))} term(s) → {out}")
        return 0
    if args.action == "learn":
        logs = []
        for t in [args.target] + (args.others or []):
            p = Path(t)
            logs += sorted(p.rglob("*.log.jsonl")) if p.is_dir() else [p]
        result = learn(logs, Path(args.lexicon), Path(args.speakers) if args.speakers else None, args.min)
        print(f"{len(logs)} log(s): {len(result['automatico'])} new ASR form(s) to add automatically, "
              f"{len(result['retido'])} held for approval, {len(result['pendente'])} pending new term(s)")
        for r in result["automatico"]:
            print(f"  + {r['termo']} ← '{r['forma']}' ({r['vezes']}×, {', '.join(r['arquivos'])})")
        for r in result["retido"]:
            print(f"  ? {r['termo']} ← '{r['forma']}' ({r['motivo']})")
        for r in result["pendente"][:30]:
            print(f"  … pending: {r['termo']} ({r['vezes']}×) forms {list(r['formas_asr'])[:4]}")
        if args.json:
            Path(args.json).write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
        if args.write:
            backup = apply_learning(Path(args.lexicon), result, Path(args.pending) if args.pending else None,
                                    Path(args.changelog) if args.changelog else None, args.label or "tcqa lexicon learn")
            print(f"lexicon updated (backup {backup})")
        else:
            print("dry run: add --write to update the lexicon")
        return 0
    return 1


def add_lexicon_parser(sub) -> None:
    p = sub.add_parser("lexicon", help="lexicon tools: hits in a raw file, validate, stats, merge, learn from logs")
    p.add_argument("action", choices=["hits", "validate", "stats", "merge", "learn"])
    p.add_argument("target", help="hits: raw file · validate/stats/merge: lexicon · learn: log file or folder")
    p.add_argument("others", nargs="*", help="merge: more lexicons · learn: more logs/folders")
    p.add_argument("--lexicon", help="hits/learn: the lexicon")
    p.add_argument("--speakers", help="hits/learn: speaker registry (its name forms count as lexicon)")
    p.add_argument("--out", help="output file (hits JSON, merged lexicon)")
    p.add_argument("--fuzzy", type=float, default=0.86, help="hits: similarity for near-matches (0-1)")
    p.add_argument("--corpus", help="validate: raw corpus folder; error forms found in most files are flagged as common words")
    p.add_argument("--common-share", type=float, default=0.15, help="validate --corpus: share of files above which a form is 'common'")
    p.add_argument("--min", type=int, default=2, help="learn: occurrences needed to add a form automatically")
    p.add_argument("--write", action="store_true", help="learn: update the lexicon (backup + changelog)")
    p.add_argument("--pending", help="learn: pending-terms file to update (new terms awaiting approval)")
    p.add_argument("--changelog", help="learn: Markdown changelog to append to")
    p.add_argument("--json", help="learn: write the full result as JSON")
    p.add_argument("--label", help="learn: run label for the changelog")
    p.set_defaults(func=cmd_lexicon)
