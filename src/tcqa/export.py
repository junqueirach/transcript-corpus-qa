"""``tcqa export``: RAG-ready chunks with metadata, one JSON object per line.

A chunk is one or more consecutive paragraphs of the same speaker, up to
``--max-words``; it never crosses a speaker turn. Each chunk carries what
retrieval and filtering need: speaker and role, channel, title, date, source
URL, file, paragraph range, quality class, markers, segment type, the lexicon
terms and people it mentions, topic tags (the lexicon categories of those
terms) and whether the corpus's main author is speaking.

Defaults follow the method's decisions: non-content segments (ads, jingles) are
left out (``--include-non-content`` keeps them, tagged), markers are kept as
written (``--markers drop`` leaves out chunks with ``[[?? ]]``), class C files
are flagged, not dropped.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .classify import parse_segments
from .layout import revised_files
from .resources import load_lexicon
from .textnorm import MARKER_RE, SPEAKER_RE, analyze, keys_of


def _mentions(text_keys: list[str], lexicon, categories: dict[tuple, str]) -> tuple[list[str], list[str]]:
    found: dict[str, str] = {}
    if lexicon is None:
        return [], []
    n = len(text_keys)
    for i in range(n):
        for size in (4, 3, 2, 1):
            if i + size > n:
                continue
            k = tuple(text_keys[i:i + size])
            term = lexicon.canonical.get(k)
            if term is None:
                continue
            if size == 1 and k[0] in COMMON_SHORT:
                continue
            found.setdefault(term, categories.get(tuple(keys_of(term)), ""))
            break
    terms = sorted(found)
    topics = sorted({c for c in found.values() if c})
    return terms, topics


COMMON_SHORT = {"obra", "vida", "era", "lei", "dan", "caos", "luz", "deus", "pra", "jesus"}


def _categories(lexicon_path: str | None) -> dict[tuple, str]:
    if not lexicon_path:
        return {}
    data = json.loads(Path(lexicon_path).read_text(encoding="utf-8"))
    return {tuple(keys_of(e.get("termo") or "")): e.get("cat") or "" for e in data.get("termos") or []}


def chunks_for(path: Path, root: Path, max_words: int = 250, include_non_content: bool = False,
               markers: str = "keep", lexicon=None, categories=None) -> list[dict]:
    doc = analyze(path.read_text(encoding="utf-8"))
    fm = doc.frontmatter or {}
    segments, _ = parse_segments(fm.get("segmentos_nao_conteudo"), len(doc.text_paragraphs))
    author = fm.get("autor_principal")
    interviewer = fm.get("entrevistador")
    mentioned = [m for m in (fm.get("mencionados") or []) if isinstance(m, str)]
    solo = isinstance(fm.get("falantes"), list) and len(fm["falantes"]) == 1
    base = {
        "arquivo": str(path.relative_to(root)).replace("\\", "/") if root in path.parents or path == root else path.name,
        "titulo": fm.get("titulo"), "canal": fm.get("canal"), "data": fm.get("data"), "tipo": fm.get("tipo"),
        "fonte_url": fm.get("fonte_url"), "idioma": fm.get("idioma"), "classe": fm.get("classe_qualidade"),
        "classe_c": fm.get("classe_qualidade") == "C", "autor_principal": author,
        "autor_principal_participa": fm.get("autor_principal_participa"), "raw_sha256": fm.get("raw_sha256"),
        "versao_revisao": fm.get("versao_revisao"),
    }
    groups: list[list] = []
    current: list = []
    words = 0
    speaker = None
    for p in doc.text_paragraphs:
        # an unlabelled paragraph continues the current turn
        label = p.speaker or (fm["falantes"][0] if solo else speaker)
        text = SPEAKER_RE.sub("", p.text, count=1).strip()
        n = len(text.split())
        kind = segments.get(p.index, "conteudo")
        if current and (label != speaker or words + n > max_words or kind != current[-1][3]):
            groups.append(current)
            current, words = [], 0
        current.append((p.index, label, text, kind))
        words += n
        speaker = label
    if current:
        groups.append(current)
    out = []
    for g in groups:
        kind = g[0][3]
        if kind != "conteudo" and not include_non_content:
            continue
        text = "\n\n".join(t for _, _, t, _ in g)
        has_unrec = "[[??" in text
        if markers == "drop" and has_unrec:
            continue
        label = g[0][1]
        keys = [k for k in keys_of(text)]
        terms, topics = _mentions(keys, lexicon, categories or {})
        people = [m for m in mentioned if tuple(keys_of(m)) and _contains(keys, keys_of(m))]
        role = ("entrevistador" if label and label == interviewer else
                "entrevistado" if label and label in (fm.get("entrevistados") or []) else
                "palestrante" if solo else None)
        out.append({**base, "id": f"{(fm.get('raw_sha256') or path.stem)[:12]}-{g[0][0]:04d}",
                    "paragrafos": [g[0][0], g[-1][0]], "falante": label, "papel": role,
                    "fala_autor_principal": bool(author and label == author),
                    "tipo_segmento": kind, "tem_marcadores": bool(MARKER_RE.search(text)),
                    "tem_irrecuperavel": has_unrec, "termos": terms, "temas": topics, "pessoas_mencionadas": people,
                    "palavras": len(text.split()), "texto": text})
    return out


def _contains(hay: list[str], needle: list[str]) -> bool:
    n = len(needle)
    return any(hay[i:i + n] == needle for i in range(len(hay) - n + 1))


def cmd_export(args: argparse.Namespace) -> int:
    target = Path(args.target)
    root = target if target.is_dir() else target.parent
    lexicon = load_lexicon(args.lexicon) if args.lexicon else None
    categories = _categories(args.lexicon)
    files = revised_files(target)
    n_chunks = 0
    out = Path(args.out)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        for path in files:
            for chunk in chunks_for(path, root, args.max_words, args.include_non_content, args.markers, lexicon, categories):
                f.write(json.dumps(chunk, ensure_ascii=False) + "\n")
                n_chunks += 1
    print(f"{n_chunks} chunk(s) from {len(files)} file(s) → {out}")
    return 0


def add_export_parser(sub) -> None:
    p = sub.add_parser("export", help="RAG-ready JSONL chunks with metadata (speaker, channel, source, class, topics…)")
    p.add_argument("target", help="revised file or folder (recursive)")
    p.add_argument("--out", required=True, help="output JSONL")
    p.add_argument("--max-words", type=int, default=250, help="maximum words per chunk (a chunk never crosses a speaker turn)")
    p.add_argument("--include-non-content", action="store_true", help="keep ads/jingles (tagged) instead of leaving them out")
    p.add_argument("--markers", choices=["keep", "drop"], default="keep", help="drop: leave out chunks with [[?? ]]")
    p.add_argument("--lexicon", help="lexicon for the 'termos' and 'temas' fields")
    p.set_defaults(func=cmd_export)
