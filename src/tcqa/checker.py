"""The fidelity checker: proves that a revised transcript differs from its raw
version only in allowed, logged ways.

Pipeline (spec 04): analyze both texts, align them word by word, classify
every differing hunk, then run checks C1..C14. It never judges whether a
correction is *right*; it proves nothing changed silently.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from . import classify as cls
from .hesitations import filler_keys, is_filler_run
from .language import detect_language, language_matches
from .log import Issue, Log, split_marker
from .resources import Lexicon, Speakers, merge_speaker_names
from .textnorm import Document, analyze, find_subsequence, keys_of

REQUIRED_FRONTMATTER = (
    "titulo", "idioma", "derivado_de", "qualidade", "raw_sha256", "revisado_em",
    "versao_revisao", "trechos_incertos", "trechos_irrecuperaveis",
    "pct_irrecuperavel", "classe_calculada", "classe_qualidade",
    "override_motivo", "apto_rag", "apto_finetuning",
)


@dataclass
class Finding:
    severity: str          # 'error' | 'warning' | 'info'
    check: str             # 'C1'..'C14', 'C0' for log problems
    message: str
    para: int | None = None
    raw: str = ""
    revised: str = ""


@dataclass
class Hunk:
    tag: str
    i1: int
    i2: int
    j1: int
    j2: int
    status: str = ""        # 'mechanical' | 'hesitation' | 'explained' | 'unexplained' | 'marker'
    entries: list[str] = field(default_factory=list)


@dataclass
class Result:
    findings: list[Finding] = field(default_factory=list)
    hunks: list[Hunk] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    review: list[dict] = field(default_factory=list)
    computed: cls.Computed | None = None

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "warning"]

    @property
    def passed(self) -> bool:
        return not self.errors

    def exit_code(self, strict: bool = False) -> int:
        if self.errors:
            return 1
        if self.warnings:
            return 1 if strict else 2
        return 0


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _span_text(tokens, a: int, b: int, body: str) -> str:
    if b <= a or not tokens:
        return ""
    a = max(a, 0)
    b = min(b, len(tokens))
    return body[tokens[a].start:tokens[b - 1].end]


def _is_text_entry(entry: dict) -> bool:
    return bool(keys_of(entry.get("raw", ""))) or bool(keys_of(entry.get("revised", "")))


class Checker:
    def __init__(self, raw_text: str, revised_text: str, log: Log | None,
                 log_issues: list[Issue], lexicon: Lexicon | None = None,
                 speakers: Speakers | None = None,
                 raw_bytes: bytes | None = None, max_deletion: int = 8,
                 finetune_languages: set[str] | None = None):
        self.raw = analyze(raw_text)
        self.rev = analyze(revised_text)
        self.log = log
        self.log_issues = log_issues
        self.lexicon = lexicon or Lexicon()
        self.speakers = speakers or Speakers()
        if self.speakers.name_forms:
            merge_speaker_names(self.lexicon, self.speakers)   # registry ASR forms of names back T1 too
        self.raw_bytes = raw_bytes
        self.max_deletion = max_deletion
        self.finetune_languages = finetune_languages
        self.result = Result()
        fm = self.rev.frontmatter or {}
        self.fm = fm if self.rev.header_kind == "yaml" else {}
        self.lang = self.fm.get("idioma") or (log.header.get("idioma") if log else None)
        # A translation is compared with its *source* (passed as RAW): the words
        # differ by design, so the word alignment is skipped and parity is checked.
        self.translation = self.fm.get("derivado_de") is not None
        self.raw_keys = [t.key for t in self.raw.tokens]
        self.rev_keys = [t.key for t in self.rev.tokens]
        self.raw_cover: dict[int, str] = {}
        self.rev_cover: dict[int, str] = {}
        self.entry_hits: dict[str, bool] = {}
        self.hesitation_deleted = 0

    # ------------------------------------------------------------ helpers
    def add(self, severity: str, check: str, message: str, para=None, raw="", revised=""):
        self.result.findings.append(Finding(severity, check, message, para, raw, revised))

    def run(self) -> Result:
        self._log_problems()
        if not self.translation:
            self._align()
            self._locate_entries()
            self._classify_hunks()
            self._phantom_entries()        # C2
            self._net_length()             # C5
        self._frontmatter_and_counts()     # C7, C8, C9
        self._speakers()                   # C10
        self._tiers()                      # C11 + review list
        self._hash()                       # C12
        if self.translation:
            self._translation()            # C13
        else:
            self._proper_names()           # C14
        self._language()
        self._accepted()
        self._stats()
        return self.result

    def _accepted(self):
        """``aceite`` log lines: a warning the reviser examined and accepted, with the
        reason, becomes 'info' (kept in the report, not counted). Errors can never be accepted."""
        if self.log is None or not self.log.accepted:
            return
        for acc in self.log.accepted:
            code, para, why = acc.get("code"), acc.get("para"), acc.get("motivo", "")
            hit = False
            for f in self.result.findings:
                if f.severity == "warning" and f.check == code and (para is None or f.para == para):
                    f.severity = "info"
                    f.message += f" — accepted: {why}"
                    hit = True
            if not hit:
                self.add("warning", "C0", f"aceite for {code}" + (f" ¶{para}" if para else "") + " matches no warning; remove it")

    # ------------------------------------------------------------ steps
    def _log_problems(self):
        if self.log is None:
            self.add("error", "C0", "log could not be loaded (no header)")
        for issue in self.log_issues:
            check = "C11" if issue.code in {"L33", "L38", "L39", "L41", "L42"} else "C0"
            self.add(issue.severity, check, f"log {issue.code}: {issue.message}" + (f" (line {issue.line})" if issue.line else ""))
        if self.log is not None:
            for e in self.log.changes:
                if str(e.get("basis") or "").lstrip().upper().startswith("TODO"):
                    self.add("error", "C0", f"entry {e.get('id')}: draft stub not completed (basis starts with TODO)", e.get("para"), e.get("raw", ""), e.get("revised", ""))
        for problem in self.rev.problems:
            self.add("error", "C3", problem)

    def _align(self):
        sm = SequenceMatcher(None, self.raw_keys, self.rev_keys, autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            self.result.hunks.append(Hunk(tag, i1, i2, j1, j2, "equal" if tag == "equal" else ""))

    def _locate_entries(self):
        """Find each log entry's raw and revised spans in the token streams and
        mark the tokens they cover."""
        if self.log is None:
            return
        diff_raw = [(h.i1, h.i2) for h in self.result.hunks if h.tag != "equal"]
        diff_rev = [(h.j1, h.j2) for h in self.result.hunks if h.tag != "equal"]

        def overlaps(a, b, ranges):
            return any(x < b and a < y or (a == b and x <= a <= y) for x, y in ranges)

        for entry in self.log.changes:
            if not _is_text_entry(entry):
                continue
            eid = entry["id"]
            rk, vk = keys_of(entry["raw"]), keys_of(entry["revised"])
            raw_hits = find_subsequence(self.raw_keys, rk) if rk else []
            rev_hits = find_subsequence(self.rev_keys, vk) if vk else []
            if rk and not raw_hits:
                self.add("error", "C2", f"entry {eid}: raw span not found in the raw file", entry.get("para"), entry["raw"], entry["revised"])
                continue
            if vk and not rev_hits:
                self.add("error", "C2", f"entry {eid}: revised span not found in the revised file", entry.get("para"), entry["raw"], entry["revised"])
                continue
            # prefer occurrences that overlap a differing hunk, then the declared paragraph
            def pick(hits, n, ranges, tokens, para, cover=None):
                scored = []
                for h in hits:
                    s = 0
                    if cover is not None and not any(k in cover for k in range(h, h + n)):
                        s += 4                      # an occurrence no other entry has claimed yet
                    if overlaps(h, h + n, ranges):
                        s += 2
                    if tokens and para and tokens[min(h, len(tokens) - 1)].para == para:
                        s += 1
                    scored.append((s, h))
                scored.sort(key=lambda x: (-x[0], x[1]))
                return scored[0][1] if scored else None
            v0 = pick(rev_hits, len(vk), diff_rev, self.rev.tokens, entry.get("para"), self.rev_cover) if vk else None
            r0 = None
            if rk:
                occ = entry.get("occurrence")
                if isinstance(occ, int) and 1 <= occ <= len(raw_hits):
                    r0 = raw_hits[occ - 1]                  # explicit: n-th occurrence in the raw file
                elif v0 is not None and len(raw_hits) > 1:
                    r0 = self._aligned_raw_hit(raw_hits, len(rk), diff_raw, v0, self.raw_cover)
                else:
                    r0 = pick(raw_hits, len(rk), diff_raw, self.raw.tokens, entry.get("para_raw"))
            if r0 is not None:
                for k in range(r0, r0 + len(rk)):
                    self.raw_cover.setdefault(k, eid)
            if v0 is not None:
                for k in range(v0, v0 + len(vk)):
                    self.rev_cover.setdefault(k, eid)
                para_found = self.rev.tokens[v0].para
                if entry.get("para") and para_found != entry["para"]:
                    self.add("warning", "C2", f"entry {eid}: 'para' says {entry['para']} but the span is in paragraph {para_found}", entry["para"], entry["raw"], entry["revised"])
            self.entry_hits[eid] = False

    def _aligned_raw_hit(self, raw_hits: list[int], n: int, diff_raw, v0: int, cover: dict) -> int:
        """Among several occurrences of a raw span, pick the one the alignment
        maps to the revised span's position (a repeated ASR error is fixed
        where it is, not at its first occurrence)."""
        expected = 0
        for h in self.result.hunks:
            if h.j1 <= v0 < max(h.j2, h.j1 + 1):
                expected = h.i1 + min(v0 - h.j1, max(h.i2 - h.i1 - 1, 0))
                break
            if h.j1 > v0:
                expected = h.i1
                break
        else:
            expected = len(self.raw_keys)
        def in_diff(h):
            return any(x < h + n and h < y for x, y in diff_raw)
        def claimed(h):
            return any(k in cover for k in range(h, h + n))
        return min(raw_hits, key=lambda h: (claimed(h), not in_diff(h), abs(h - expected), h))

    def _inside_marker(self, j1: int, j2: int) -> bool:
        toks = self.rev.tokens
        if j2 > j1:
            return any(t.marker for t in toks[j1:j2])
        if 0 < j1 < len(toks):
            return bool(toks[j1 - 1].marker and toks[j1].marker and toks[j1 - 1].para == toks[j1].para)
        return False

    def _classify_hunks(self):
        fillers = filler_keys(self.lang)
        for h in self.result.hunks:
            if h.tag == "equal":
                continue
            raw_side = self.raw_keys[h.i1:h.i2]
            rev_side = self.rev_keys[h.j1:h.j2]
            raw_txt = _span_text(self.raw.tokens, h.i1, h.i2, self.raw.body)
            rev_txt = _span_text(self.rev.tokens, h.j1, h.j2, self.rev.body)
            para = self.rev.tokens[min(h.j1, len(self.rev.tokens) - 1)].para if self.rev.tokens else None

            if self._inside_marker(h.j1, h.j2):
                h.status = "marker"
                self.add("error", "C3", "text inside a marker differs from the raw text (nothing may change inside [[ ]])", para, raw_txt, rev_txt)
                continue

            before = self.raw_keys[h.i1 - 1] if h.i1 > 0 else None
            after = self.raw_keys[h.i2] if h.i2 < len(self.raw_keys) else None
            if h.tag == "delete" and is_filler_run(raw_side, before, after, self.lang):
                h.status = "hesitation"
                self.hesitation_deleted += len(raw_side)
                self._credit_entries(h)
                continue
            if h.tag == "replace":
                kept, prev = [], before
                for k in raw_side:
                    if k in fillers or (prev is not None and k == prev):
                        prev = k
                        continue
                    kept.append(k)
                    prev = k
                if kept == rev_side:
                    h.status = "hesitation"
                    self.hesitation_deleted += len(raw_side) - len(rev_side)
                    self._credit_entries(h)
                    continue

            # needs log coverage
            missing_raw, prev = [], before
            for k in range(h.i1, h.i2):
                key = self.raw_keys[k]
                if k in self.raw_cover:
                    h.entries.append(self.raw_cover[k])
                elif key in fillers or (prev is not None and key == prev) or (after is not None and key == after):
                    self.hesitation_deleted += 1
                else:
                    missing_raw.append(key)
                prev = key
            missing_rev = []
            for k in range(h.j1, h.j2):
                if k in self.rev_cover:
                    h.entries.append(self.rev_cover[k])
                else:
                    missing_rev.append(self.rev_keys[k])
            h.entries = sorted(set(h.entries))
            for eid in h.entries:
                self.entry_hits[eid] = True
            if not missing_raw and not missing_rev:
                h.status = "explained"
                continue
            h.status = "unexplained"
            hint = ""
            canon = self.lexicon.canonical_for(raw_side)
            if canon and self.lexicon.is_canonical(rev_side):
                hint = f" (lexicon variant of '{canon}': needs a T1 entry)"
            if h.tag == "delete" and len(raw_side) >= self.max_deletion:
                self.add("error", "C4", f"silent deletion of {len(raw_side)} consecutive words without a log entry", para, raw_txt, rev_txt)
            elif h.tag == "insert":
                self.add("error", "C6", "words added that are neither in the raw text nor in the log", para, raw_txt, rev_txt)
            else:
                self.add("error", "C1", "difference without a log entry" + hint, para, raw_txt, rev_txt)

    def _credit_entries(self, h: Hunk) -> None:
        """A logged removal that the checker would also accept as a filler/noise
        removal is not a phantom entry: credit it."""
        for k in range(h.i1, h.i2):
            if k in self.raw_cover:
                self.entry_hits[self.raw_cover[k]] = True
                h.entries.append(self.raw_cover[k])

    def _phantom_entries(self):
        if self.log is None:
            return
        for entry in self.log.changes:
            eid = entry["id"]
            if eid not in self.entry_hits or self.entry_hits[eid]:
                continue
            if keys_of(entry["raw"]) == keys_of(entry["revised"]):
                if entry.get("marker") is None:
                    self.add("warning", "C2", f"entry {eid}: raw and revised are the same words; the entry changes nothing", entry.get("para"), entry["raw"], entry["revised"])
                continue
            self.add("warning", "C2", f"entry {eid}: no difference in the text corresponds to this entry", entry.get("para"), entry["raw"], entry["revised"])

    def _net_length(self):
        raw_n = len(self.raw.tokens) - self.hesitation_deleted
        rev_n = len(self.rev.tokens)
        if raw_n > 0 and rev_n < 0.9 * raw_n:
            self.add("warning", "C5", f"revised text has {rev_n} words, below 90% of the raw ({raw_n} after removing fillers)")

    def _frontmatter_and_counts(self):
        if self.rev.header_kind != "yaml":
            self.add("error", "C7", "revised file has no YAML front matter")
            return
        fm = self.fm
        for key in REQUIRED_FRONTMATTER:
            if key not in fm:
                self.add("error", "C7", f"front matter missing '{key}'")
        derived = fm.get("derivado_de") is not None
        comp = cls.compute(self.rev, derived=derived, language=fm.get("idioma"), finetune_languages=self.finetune_languages)
        self.result.computed = comp
        expected = {
            "trechos_incertos": comp.trechos_incertos,
            "trechos_irrecuperaveis": comp.trechos_irrecuperaveis,
            "pct_irrecuperavel": comp.pct_irrecuperavel,
            "classe_calculada": comp.classe_calculada,
        }
        if "palavras_corpo" in fm:
            expected["palavras_corpo"] = comp.palavras_corpo
        if "secao_degradada" in fm:
            expected["secao_degradada"] = comp.secao_degradada
        if self.log is not None:
            expected["termos_corrigidos"] = sum(1 for e in self.log.changes if e.get("tier") == "T1" and str(e.get("basis", "")).startswith("lexicon:"))
        for key, value in expected.items():
            if key not in fm:
                continue
            got = fm[key]
            if key == "pct_irrecuperavel":
                ok = isinstance(got, (int, float)) and abs(float(got) - value) < 0.051
            else:
                ok = got == value
            if not ok:
                check = "C8" if key == "classe_calculada" else "C7"
                self.add("error", check, f"front matter {key} = {got!r} but the text gives {value!r}")
        # non-content segments (ads, jingles): valid paragraphs, and their share of words if declared
        segments, seg_problems = cls.parse_segments(fm.get("segmentos_nao_conteudo"), len(self.rev.text_paragraphs))
        for problem in seg_problems:
            self.add("error", "C7", problem)
        if "pct_nao_conteudo" in fm:
            share = cls.non_content_share(self.rev, segments)
            got = fm["pct_nao_conteudo"]
            if not (isinstance(got, (int, float)) and abs(float(got) - share) < 0.051):
                self.add("error", "C7", f"front matter pct_nao_conteudo = {got!r} but the tagged segments give {share!r}")
        # C8 class and override
        declared = fm.get("classe_qualidade")
        ok, why = cls.override_ok(comp.classe_calculada, declared, fm.get("override_motivo"))
        if not ok:
            self.add("error", "C8", why)
        if self.log is not None:
            for key in ("classe_calculada", "classe_qualidade", "override_motivo"):
                if key in fm and self.log.header.get(key) != fm.get(key):
                    self.add("error", "C8", f"log header {key} = {self.log.header.get(key)!r} differs from front matter {fm.get(key)!r}")
        # C9 flags: computed from the declared class (an accepted override moves the flag too)
        klass = declared if ok and declared in cls.CLASSES else comp.classe_calculada
        lang_ok = True
        if self.finetune_languages is not None:
            lang_ok = (fm.get("idioma") or "").split("-")[0].casefold() in {l.split("-")[0].casefold() for l in self.finetune_languages}
        exp_ft = klass in ("A", "B") and not derived and lang_ok
        if "apto_finetuning" in fm and fm["apto_finetuning"] != exp_ft:
            self.add("error", "C9", f"apto_finetuning = {fm['apto_finetuning']!r} but the rules give {exp_ft!r} (class {klass}, derived={derived})")
        if "apto_rag" in fm and fm["apto_rag"] != comp.apto_rag:
            self.add("error", "C9", f"apto_rag = {fm['apto_rag']!r} but the rules give {comp.apto_rag!r}")

    def _speakers(self):
        proposed = {}
        if self.log is not None:
            for e in self.log.changes:
                fn = e.get("falante_novo")
                if isinstance(fn, dict) and fn.get("nome"):
                    proposed[fn["nome"].strip()] = fn.get("citacao", "")
        seen = set()
        for para, label in self.rev.speakers:
            if label in seen:
                continue
            seen.add(label)
            if self.speakers.allowed(label):
                continue
            if label in proposed:
                self.add("warning", "C10", f"speaker '{label}' is proposed in the log (quote: {proposed[label]!r}) and awaits approval", para)
                self.result.review.append({"kind": "falante_novo", "nome": label, "citacao": proposed[label], "para": para})
            else:
                self.add("error", "C10", f"speaker label '{label}' is neither in the registry nor in the generic list", para, "", f"**[{label}]**")
        falantes = self.fm.get("falantes")
        if isinstance(falantes, list) and len(falantes) == 1 and self.rev.speakers:
            self.add("error", "C10", "solo talk (one name in 'falantes') but the text has speaker labels")
        if isinstance(falantes, list) and len(falantes) > 1 and not self.rev.speakers:
            self.add("warning", "C10", "several speakers declared but no speaker labels in the text")
        # the front matter must list the people the text actually labels, and only them
        used = list(dict.fromkeys(label for _, label in self.rev.speakers))
        if isinstance(falantes, list) and len(falantes) > 1 and used:
            declared = {str(x).strip() for x in falantes}
            for label in used:
                if label not in declared:
                    self.add("warning", "C10", f"speaker label '{label}' is used in the text but not listed in 'falantes'")
            for name in declared - set(used):
                self.add("warning", "C10", f"'{name}' is listed in 'falantes' but labels no turn in the text")
        # corpus control: does the main author speak in this file?
        author = self.fm.get("autor_principal")
        takes_part = self.fm.get("autor_principal_participa")
        if author and isinstance(takes_part, bool):
            speaks = author in used or (isinstance(falantes, list) and len(falantes) == 1 and falantes[0] == author)
            if takes_part and not speaks:
                self.add("warning", "C10", f"autor_principal_participa is true but '{author}' labels no turn and is not the solo speaker")
            if not takes_part and author in used:
                self.add("error", "C10", f"autor_principal_participa is false but '{author}' is a speaker label in the text")

    def _tiers(self):
        if self.log is None:
            return
        for e in self.log.changes:
            tier, conf, marker = e.get("tier"), e.get("confidence"), e.get("marker")
            if tier in ("T3", "T4") or conf in ("medium", "low"):
                self.result.review.append({"kind": "entry", **{k: e.get(k) for k in ("id", "para", "raw", "revised", "tier", "basis", "confidence", "marker", "categoria")}})
            if tier == "T4" and marker is None and conf != "high":
                self.add("error", "C11", f"entry {e['id']}: T4 correction written into the text with confidence {conf!r}", e.get("para"), e["raw"], e["revised"])
            basis = str(e.get("basis") or "")
            if tier == "T4" and marker is None and self.lexicon.loaded:
                # outside knowledge is not needed for a term the corpus lexicon already has: that is T1 (listed form) or T2
                terms = self.lexicon.terms_written(e.get("revised", ""), e.get("raw", ""))
                if terms:
                    self.add("warning", "C11", f"entry {e['id']}: T4 writes the lexicon term '{terms[0]}'; log it as T1 (listed form) or T2 citing the lexicon entry",
                             e.get("para"), e["raw"], e["revised"])
            if tier == "T1" and basis.startswith("lexicon:") and marker is None:
                term = basis[len("lexicon:"):].strip()
                if not self.lexicon.loaded:
                    self.add("warning", "C11", f"entry {e['id']}: T1 lexicon basis not verified (no lexicon supplied)", e.get("para"), e["raw"], e["revised"])
                else:
                    why = self.lexicon.supports_t1(term, e.get("raw", ""), e.get("revised", ""))
                    if why:
                        self.add("error", "C11", f"entry {e['id']}: T1 lexicon basis not supported: {why}; use T2 with context, or add the form to the lexicon", e.get("para"), e["raw"], e["revised"])
                    elif self.lexicon.is_homophone(term):
                        # the term collides with a common word: the lexicon alone does not prove it was meant
                        self.add("warning", "C11", f"entry {e['id']}: '{term}' has high homophony risk; confirm from context that the term is meant", e.get("para"), e["raw"], e["revised"])
                        self.result.review.append({"kind": "entry", "why": "homofonia", **{k: e.get(k) for k in ("id", "para", "raw", "revised", "tier", "basis", "confidence", "marker", "categoria")}})

    def _hash(self):
        if self.raw_bytes is None:
            self.add("warning", "C12", "raw bytes not supplied; hash not verified")
            return
        actual = sha256_bytes(self.raw_bytes)
        declared = self.fm.get("raw_sha256")
        if declared != actual:
            self.add("error", "C12", f"front matter raw_sha256 does not match the raw file ({str(declared)[:12]}… vs {actual[:12]}…)")
        if self.log is not None and self.log.header.get("raw_sha256") != actual:
            self.add("error", "C12", "log header raw_sha256 does not match the raw file")
        self.result.stats["raw_sha256"] = actual

    def _translation(self):
        """C13: the RAW argument is the *source* revised file of the translation."""
        src, tr = self.raw, self.rev
        if src.header_kind != "yaml":
            self.add("error", "C13", "for a translation, pass its source revised file (with front matter) as RAW")
            return
        if self.fm.get("derivado_de") and src.frontmatter and src.frontmatter.get("derivado_de") is not None:
            self.add("error", "C13", "the source of a translation must itself be a source transcript, not another derived file")
        if len(src.text_paragraphs) != len(tr.text_paragraphs):
            self.add("error", "C13", f"translation has {len(tr.text_paragraphs)} paragraphs, source has {len(src.text_paragraphs)}")
        src_m = [(m.kind, " ".join(m.original.split())) for m in src.markers]
        tr_m = [(m.kind, " ".join(m.original.split())) for m in tr.markers]
        if [k for k, _ in src_m] != [k for k, _ in tr_m]:
            self.add("error", "C13", f"marker sequence differs: source {[k for k, _ in src_m]}, translation {[k for k, _ in tr_m]}")
        else:
            for (sk, st), (tk, tt), m in zip(src_m, tr_m, tr.markers):
                if sk == "??" and st != tt:
                    self.add("error", "C13", "[[?? ]] content was translated or altered; it must stay identical to the source", m.para, st, tt)
        if self.fm.get("apto_finetuning") is True:
            self.add("error", "C13", "a translation can not be apto_finetuning (decision D4)")

    def _proper_names(self):
        raw_set = set(self.raw_keys)
        lex_words = self.lexicon.canonical_words()
        seen = set()
        for idx, t in enumerate(self.rev.tokens):
            if t.marker or not t.text[:1].isupper() or t.key in raw_set or t.key in seen:
                continue
            seen.add(t.key)
            if idx in self.rev_cover or t.key in lex_words:
                continue
            self.add("error", "C14", f"capitalised word '{t.text}' is absent from the raw text, the log and the lexicon", t.para, "", t.text)

    def _language(self):
        detected, conf = detect_language(self.rev.body)
        self.result.stats["language_detected"] = detected
        declared = self.fm.get("idioma")
        if detected and declared and not language_matches(declared, detected):
            self.add("warning", "C7", f"front matter idioma = {declared!r} but the text looks like {detected!r}")
        if declared is None and "idioma" in self.fm:
            self.add("warning", "C7", "idioma is null; run 'tcqa classify' to detect it")

    def _stats(self):
        hunks = [h for h in self.result.hunks if h.tag != "equal"]
        st = self.result.stats
        st.update({
            "raw_words": len(self.raw.tokens),
            "revised_words": len(self.rev.tokens),
            "hunks": len(hunks),
            "hesitation_hunks": sum(1 for h in hunks if h.status == "hesitation"),
            "hesitation_words_removed": self.hesitation_deleted,
            "explained_hunks": sum(1 for h in hunks if h.status == "explained"),
            "unexplained_hunks": sum(1 for h in hunks if h.status == "unexplained"),
            "marker_violations": sum(1 for h in hunks if h.status == "marker"),
            "markers_?": self.rev.count_markers("?"),
            "markers_??": self.rev.count_markers("??"),
            "accent_or_case_only": sum(
                1 for h in self.result.hunks if h.tag == "equal"
                for a, b in zip(self.raw.tokens[h.i1:h.i2], self.rev.tokens[h.j1:h.j2]) if a.text != b.text),
            "log_entries": len(self.log.changes) if self.log else 0,
        })


def run_check(raw_text: str, revised_text: str, log: Log | None, log_issues: list[Issue], **kw) -> Result:
    return Checker(raw_text, revised_text, log, log_issues, **kw).run()
