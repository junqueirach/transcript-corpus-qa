"""Computed quality fields: counts, class A/B/C, section rule, readiness flags.

Rule R3/R6 of the method. Thresholds are module constants so that a test can
read them and the README can quote them.
"""
from __future__ import annotations

from dataclasses import dataclass

from .textnorm import Document

CLASS_B_MAX_PCT = 2.0          # share of body words inside [[?? ]] (percent)
SECTION_MAX_SHARE = 0.25       # a "section" holds at most 25 % of the words
SECTION_MIN_BAD_SHARE = 0.75   # ... and at least 75 % of the unrecoverable words
RAG_UNREADABLE_PCT = 50.0      # above this the file is not even searchable
CLASSES = ("A", "B", "C")
SEGMENT_TYPES = ("anuncio", "vinheta", "abertura", "encerramento", "outro")   # non-content speech (decision F4)


def parse_segments(value, n_paras: int) -> tuple[dict[int, str], list[str]]:
    """``segmentos_nao_conteudo``: a one-line list of ``"<paras>:<tipo>"`` items, where
    paras is ``3`` or ``3-5`` (front matter has no nested blocks), e.g.
    ``["1:anuncio", "29-30:anuncio"]``.

    Returns {paragraph: type} and a list of problems. Tagged paragraphs stay in
    the transcript; exporters leave them out by default.
    """
    out: dict[int, str] = {}
    problems: list[str] = []
    if value in (None, []):
        return out, problems
    if not isinstance(value, list):
        return out, ["segmentos_nao_conteudo must be a list like [\"1:anuncio\", \"29-30:anuncio\"]"]
    for i, seg in enumerate(value, 1):
        if isinstance(seg, str) and ":" in seg:
            paras_txt, kind = (x.strip() for x in seg.rsplit(":", 1))
            seg = {"paras": paras_txt, "tipo": kind}
        if not isinstance(seg, dict):
            problems.append(f"segmentos_nao_conteudo[{i}] must look like \"3-5:anuncio\"")
            continue
        kind = seg.get("tipo")
        if kind not in SEGMENT_TYPES:
            problems.append(f"segmentos_nao_conteudo[{i}]: tipo {kind!r} is not one of {list(SEGMENT_TYPES)}")
        paras = seg.get("paras")
        nums: list[int] = []
        items = paras if isinstance(paras, list) else [paras]
        for item in items:
            if isinstance(item, int):
                nums.append(item)
            elif isinstance(item, str) and "-" in item and all(x.strip().isdigit() for x in item.split("-", 1)):
                a, b = (int(x) for x in item.split("-", 1))
                nums.extend(range(a, b + 1))
            elif isinstance(item, str) and item.strip().isdigit():
                nums.append(int(item))
            else:
                problems.append(f"segmentos_nao_conteudo[{i}]: paras {paras!r} is not a number, list or range 'a-b'")
        for n in nums:
            if not 1 <= n <= n_paras:
                problems.append(f"segmentos_nao_conteudo[{i}]: paragraph {n} does not exist (1-{n_paras})")
            else:
                out[n] = kind or "outro"
    return out, problems


def non_content_share(doc: Document, segments: dict[int, str]) -> float:
    words = sum(1 for t in doc.tokens if t.para in segments)
    return pct(words, len(doc.tokens))


@dataclass
class Computed:
    palavras_corpo: int
    trechos_incertos: int
    trechos_irrecuperaveis: int
    palavras_irrecuperaveis: int
    pct_irrecuperavel: float
    secao_degradada: str | None
    classe_calculada: str
    apto_rag: bool
    apto_finetuning: bool

    def as_frontmatter(self) -> dict:
        return {
            "palavras_corpo": self.palavras_corpo,
            "trechos_incertos": self.trechos_incertos,
            "trechos_irrecuperaveis": self.trechos_irrecuperaveis,
            "pct_irrecuperavel": self.pct_irrecuperavel,
            "secao_degradada": self.secao_degradada,
            "classe_calculada": self.classe_calculada,
            "apto_rag": self.apto_rag,
            "apto_finetuning": self.apto_finetuning,
        }


def pct(part: int, whole: int) -> float:
    return round(100.0 * part / whole, 2) if whole else 0.0


def class_from_pct(value: float) -> str:
    if value == 0:
        return "A"
    if value <= CLASS_B_MAX_PCT:
        return "B"
    return "C"


def degraded_section(doc: Document) -> str | None:
    """Rule R3.3: find one contiguous run of paragraphs with <= 25 % of the
    words that holds >= 75 % of the unrecoverable words, such that the rest of
    the file alone is within the class-B limit. Returns '§a–§b' or None."""
    paras = doc.text_paragraphs
    words = {p.index: 0 for p in paras}
    bad = {p.index: 0 for p in paras}
    for t in doc.tokens:
        words[t.para] = words.get(t.para, 0) + 1
        if t.marker == "??":
            bad[t.para] = bad.get(t.para, 0) + 1
    total_w, total_b = sum(words.values()), sum(bad.values())
    if total_w == 0 or total_b == 0:
        return None
    if pct(total_b, total_w) <= CLASS_B_MAX_PCT:
        return None
    order = [p.index for p in paras]
    best: tuple[int, int] | None = None
    for i in range(len(order)):
        w = b = 0
        for j in range(i, len(order)):
            w += words[order[j]]
            b += bad[order[j]]
            if w > SECTION_MAX_SHARE * total_w:
                break
            rest_w, rest_b = total_w - w, total_b - b
            if b >= SECTION_MIN_BAD_SHARE * total_b and pct(rest_b, rest_w) <= CLASS_B_MAX_PCT:
                if best is None or (order[j] - order[i]) < (best[1] - best[0]):
                    best = (order[i], order[j])
                break
    if best is None:
        return None
    return f"§{best[0]}–§{best[1]}" if best[0] != best[1] else f"§{best[0]}"


def compute(doc: Document, derived: bool = False, language: str | None = None,
            finetune_languages: set[str] | None = None) -> Computed:
    total = len(doc.tokens)
    bad_words = doc.words_in_markers("??")
    share = pct(bad_words, total)
    section = degraded_section(doc)
    klass = "B" if section else class_from_pct(share)
    apto_rag = share <= RAG_UNREADABLE_PCT
    lang_ok = True
    if finetune_languages is not None:
        base = (language or "").split("-")[0].casefold()
        lang_ok = base in {l.split("-")[0].casefold() for l in finetune_languages}
    apto_ft = klass in ("A", "B") and not derived and lang_ok
    return Computed(
        palavras_corpo=total,
        trechos_incertos=doc.count_markers("?"),
        trechos_irrecuperaveis=doc.count_markers("??"),
        palavras_irrecuperaveis=bad_words,
        pct_irrecuperavel=share,
        secao_degradada=section,
        classe_calculada=klass,
        apto_rag=apto_rag,
        apto_finetuning=apto_ft,
    )


def override_ok(calculated: str, declared: str, reason: str | None) -> tuple[bool, str]:
    """R3.4: declared class may differ from the calculated one by one step
    with a non-empty reason. Returns (ok, explanation)."""
    if calculated == declared:
        return True, "class equals the computed class"
    if calculated not in CLASSES or declared not in CLASSES:
        return False, "class must be A, B or C"
    steps = abs(CLASSES.index(calculated) - CLASSES.index(declared))
    if steps > 1:
        return False, f"override of two steps ({calculated} -> {declared}) is never allowed"
    if not (isinstance(reason, str) and reason.strip()):
        return False, f"class {declared} differs from computed {calculated} without override_motivo"
    return True, f"one-step override {calculated} -> {declared} with reason"
