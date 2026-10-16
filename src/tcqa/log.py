"""Structured correction log: loading and validation (JSON Lines).

The log has one JSON object per line. Line 1 is the header; every other line is
a ``change`` (one edit), a ``bulk`` (a count of mechanical edits: hunks, not
characters) or an ``aceite`` (a checker warning the reviser examined and accepted,
with the reason).
The rules enforced here mirror ``schema/log.schema.json`` and need no library.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

CATEGORIES = {
    "pontuacao", "nome", "termo", "sentido", "falante", "ruido",
    "hesitacao", "marcacao", "insercao", "remocao", "traducao",
}
BULK_CATEGORIES = {"pontuacao", "hesitacao", "ruido"}
TIERS = {"T1", "T2", "T3", "T4"}
CONFIDENCES = {"high", "medium", "low"}
CLASSES = ("A", "B", "C")
MARKERS = {"?", "??"}

HEADER_REQUIRED = (
    "type", "file", "raw_sha256", "idioma", "derivado_de", "versao_revisao",
    "revisado_em", "revisado_por", "classe_calculada", "classe_qualidade",
    "override_motivo",
)
CHANGE_REQUIRED = (
    "type", "id", "para", "raw", "revised", "categoria", "tier", "basis",
    "confidence", "marker",
)
CHANGE_ALLOWED = set(CHANGE_REQUIRED) | {"para_raw", "falante_novo", "notas", "occurrence"}
ACCEPT_ALLOWED = {"type", "code", "motivo", "para", "notas"}
CHECK_CODE_RE = re.compile(r"^C\d{1,2}$")
# T3 basis: another transcript of the corpus, or one of the author's works (decision C2)
T3_PREFIXES = ("crossfile:", "obra:")
T3_CITATION_RE = re.compile(r"¶\s*\d+|§\s*\d+|para(?:graph)?\s*\d+|\bp(?:ág)?\.?\s*\d+|\bcap(?:ítulo)?\.?\s*\w+", re.IGNORECASE)

SHA_RE = re.compile(r"^[0-9a-f]{64}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ID_RE = re.compile(r"^c\d{4,}$")

# The suggestion arrow (U+27F6) and the two accepted labels after it.
ARROW = "⟶"
SUGGESTION_RE = re.compile(r"\s" + ARROW + r"\s(?:sugest[aã]o|suggestion):\s")


@dataclass
class Issue:
    """One validation problem. ``severity`` is 'error' or 'warning'."""
    severity: str
    code: str
    message: str
    line: int | None = None

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        where = f"line {self.line}: " if self.line else ""
        return f"[{self.severity}] {self.code} {where}{self.message}"


@dataclass
class Log:
    header: dict
    changes: list[dict] = field(default_factory=list)
    bulks: list[dict] = field(default_factory=list)
    lines: list[dict] = field(default_factory=list)
    accepted: list[dict] = field(default_factory=list)


def parse_jsonl(text: str) -> tuple[list[dict], list[Issue]]:
    """Parse JSON Lines. Blank lines are ignored. Bad JSON becomes an error."""
    objects: list[dict] = []
    issues: list[Issue] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            issues.append(Issue("error", "L00", f"invalid JSON: {exc.msg}", number))
            continue
        if not isinstance(obj, dict):
            issues.append(Issue("error", "L00", "line is not a JSON object", number))
            continue
        obj["_line"] = number
        objects.append(obj)
    return objects, issues


def split_marker(revised: str) -> tuple[str, str, str | None] | None:
    """Split a marker string into (kind, original, suggestion).

    ``[[? abc ⟶ sugestão: xyz ]]`` -> ('?', 'abc', 'xyz'); returns None when
    ``revised`` is not exactly one marker.
    """
    m = re.fullmatch(r"\[\[(\?\??)\s(.*?)\s\]\]", revised.strip(), flags=re.S)
    if not m:
        return None
    kind, inner = m.group(1), m.group(2)
    parts = SUGGESTION_RE.split(inner, maxsplit=1)
    if len(parts) == 2:
        return kind, parts[0], parts[1]
    return kind, inner, None


def _check_header(obj: dict, issues: list[Issue]) -> None:
    ln = obj["_line"]
    for key in HEADER_REQUIRED:
        if key not in obj:
            issues.append(Issue("error", "L10", f"header missing field '{key}'", ln))
    sha = obj.get("raw_sha256")
    if isinstance(sha, str) and not SHA_RE.match(sha):
        issues.append(Issue("error", "L11", "raw_sha256 is not a 64-char lowercase hex string", ln))
    if "versao_revisao" in obj and (not isinstance(obj["versao_revisao"], int) or obj["versao_revisao"] < 1):
        issues.append(Issue("error", "L12", "versao_revisao must be an integer >= 1", ln))
    if "revisado_em" in obj and not (isinstance(obj["revisado_em"], str) and DATE_RE.match(obj["revisado_em"])):
        issues.append(Issue("error", "L13", "revisado_em must be YYYY-MM-DD", ln))
    calc, final = obj.get("classe_calculada"), obj.get("classe_qualidade")
    if final not in CLASSES:
        issues.append(Issue("error", "L14", "classe_qualidade must be A, B or C", ln))
    if calc is not None and calc not in CLASSES:
        issues.append(Issue("error", "L14", "classe_calculada must be A, B, C or null", ln))
    if calc in CLASSES and final in CLASSES and calc != final:
        motive = obj.get("override_motivo")
        if not (isinstance(motive, str) and motive.strip()):
            issues.append(Issue("error", "L15", f"classe_qualidade {final} differs from classe_calculada {calc} without override_motivo", ln))
        if abs(CLASSES.index(calc) - CLASSES.index(final)) > 1:
            issues.append(Issue("error", "L16", f"override of two steps ({calc} -> {final}) is never allowed", ln))
    if "falante_nativo" in obj and obj["falante_nativo"] not in (True, False, None):
        issues.append(Issue("error", "L17", "falante_nativo must be true, false or null", ln))


def _check_change(obj: dict, issues: list[Issue], seen_ids: set[str]) -> None:
    ln = obj["_line"]
    for key in CHANGE_REQUIRED:
        if key not in obj:
            issues.append(Issue("error", "L20", f"change missing field '{key}'", ln))
    extra = set(obj) - CHANGE_ALLOWED - {"_line"}
    if extra:
        issues.append(Issue("error", "L21", f"unknown field(s) {sorted(extra)}", ln))
    cid = obj.get("id")
    if not (isinstance(cid, str) and ID_RE.match(cid)):
        issues.append(Issue("error", "L22", "id must look like c0001", ln))
    elif cid in seen_ids:
        issues.append(Issue("error", "L23", f"duplicate id {cid}", ln))
    else:
        seen_ids.add(cid)
    if not (isinstance(obj.get("para"), int) and obj["para"] >= 1):
        issues.append(Issue("error", "L24", "para must be an integer >= 1", ln))
    if "occurrence" in obj and not (isinstance(obj["occurrence"], int) and obj["occurrence"] >= 1):
        issues.append(Issue("error", "L45", "occurrence must be an integer >= 1 (which occurrence of the raw span in its paragraph)", ln))
    raw, revised = obj.get("raw"), obj.get("revised")
    if not isinstance(raw, str) or not isinstance(revised, str):
        issues.append(Issue("error", "L25", "raw and revised must be strings", ln))
        return
    cat, tier, conf, marker = obj.get("categoria"), obj.get("tier"), obj.get("confidence"), obj.get("marker")
    if cat not in CATEGORIES:
        issues.append(Issue("error", "L26", f"unknown categoria {cat!r}", ln))
    if tier is not None and tier not in TIERS:
        issues.append(Issue("error", "L27", f"unknown tier {tier!r}", ln))
    if conf is not None and conf not in CONFIDENCES:
        issues.append(Issue("error", "L28", f"unknown confidence {conf!r}", ln))
    if marker is not None and marker not in MARKERS:
        issues.append(Issue("error", "L29", f"marker must be '?', '??' or null, got {marker!r}", ln))
    basis = obj.get("basis")

    if marker is not None:
        # A marker entry wraps the raw span unchanged.
        parsed = split_marker(revised)
        if parsed is None:
            issues.append(Issue("error", "L30", "marker entry: revised is not exactly one [[? ]] / [[?? ]] marker", ln))
        else:
            kind, original, _suggestion = parsed
            if kind != marker:
                issues.append(Issue("error", "L31", f"marker field is {marker!r} but revised uses {kind!r}", ln))
            if original != raw:
                issues.append(Issue("error", "L32", "marker entry: text inside the marker differs from raw (nothing may change inside a marker)", ln))
        if conf == "high":
            issues.append(Issue("error", "L33", "marker entry with confidence high: a suggestion inside a marker carries medium or low; if you are sure, log a correction instead", ln))
        if parsed is not None and parsed[2] is not None and conf is None:
            issues.append(Issue("error", "L34", "marker entry with a suggestion needs confidence medium or low", ln))
        return

    # Non-marker entry: the text was actually altered.
    if raw == "" and cat not in ("insercao", "falante"):
        issues.append(Issue("error", "L35", "raw == '' requires categoria 'insercao' or 'falante'", ln))
    if revised == "" and cat not in ("remocao", "ruido", "hesitacao"):
        issues.append(Issue("error", "L36", "revised == '' requires categoria 'remocao', 'ruido' or 'hesitacao'", ln))
    if raw == revised:
        issues.append(Issue("warning", "L37", "raw and revised are identical: entry changes nothing", ln))
    if tier is None:
        issues.append(Issue("error", "L38", "a change written into the text needs a tier (T1-T4)", ln))
    if conf != "high":
        issues.append(Issue("error", "L39", f"confidence {conf!r} may not be written into the text; only 'high' changes text, medium/low become a marker with a suggestion", ln))
    if not (isinstance(basis, str) and basis.strip()):
        issues.append(Issue("error", "L40", "basis is required for every change", ln))
    else:
        prefixes = {"T2": ("context:",), "T3": T3_PREFIXES, "T4": ("external:",)}.get(tier)
        if prefixes and not basis.startswith(prefixes):
            issues.append(Issue("error", "L41", f"{tier} entries need a basis starting with {' or '.join(repr(x) for x in prefixes)}", ln))
        if tier == "T3" and basis.startswith("crossfile:") and not re.search(r"¶\s*\d+|§\s*\d+|para(?:graph)?\s*\d+", basis):
            issues.append(Issue("error", "L42", "T3 basis must cite the paragraph of the other file (e.g. 'crossfile: other.md ¶12')", ln))
        if tier == "T3" and basis.startswith("obra:") and not T3_CITATION_RE.search(basis):
            issues.append(Issue("error", "L42", "T3 basis from a work must cite where (e.g. 'obra: Title, p. 45' or 'cap. 3')", ln))
    if cat == "falante":
        fn = obj.get("falante_novo")
        if fn is not None and not (isinstance(fn, dict) and fn.get("nome") and fn.get("citacao")):
            issues.append(Issue("error", "L43", "falante_novo needs 'nome' and 'citacao'", ln))
    elif "falante_novo" in obj:
        issues.append(Issue("error", "L44", "falante_novo is only valid on categoria 'falante'", ln))


def _check_bulk(obj: dict, issues: list[Issue]) -> None:
    ln = obj["_line"]
    if obj.get("categoria") not in BULK_CATEGORIES:
        issues.append(Issue("error", "L50", f"bulk categoria must be one of {sorted(BULK_CATEGORIES)}", ln))
    if not (isinstance(obj.get("count"), int) and obj["count"] >= 0):
        issues.append(Issue("error", "L51", "bulk count must be an integer >= 0", ln))
    extra = set(obj) - {"type", "categoria", "count", "notas", "_line"}
    if extra:
        issues.append(Issue("error", "L52", f"unknown field(s) {sorted(extra)}", ln))


def _check_accept(obj: dict, issues: list[Issue]) -> None:
    ln = obj["_line"]
    if not (isinstance(obj.get("code"), str) and CHECK_CODE_RE.match(obj["code"])):
        issues.append(Issue("error", "L60", "aceite needs 'code' naming the check (e.g. 'C5')", ln))
    if not (isinstance(obj.get("motivo"), str) and obj["motivo"].strip()):
        issues.append(Issue("error", "L61", "aceite needs 'motivo': why the warning is accepted", ln))
    if "para" in obj and not (isinstance(obj["para"], int) and obj["para"] >= 1):
        issues.append(Issue("error", "L62", "aceite 'para' must be an integer >= 1", ln))
    extra = set(obj) - ACCEPT_ALLOWED - {"_line"}
    if extra:
        issues.append(Issue("error", "L63", f"unknown field(s) {sorted(extra)}", ln))


def validate_objects(objects: list[dict]) -> list[Issue]:
    """Validate parsed log objects. Returns issues (empty list = valid)."""
    issues: list[Issue] = []
    if not objects:
        return [Issue("error", "L01", "log is empty")]
    first = objects[0]
    if first.get("type") != "header":
        issues.append(Issue("error", "L02", "first line must be the header", first["_line"]))
    headers = [o for o in objects if o.get("type") == "header"]
    if len(headers) > 1:
        issues.append(Issue("error", "L03", f"{len(headers)} header lines; exactly one is allowed"))
    seen_ids: set[str] = set()
    for obj in objects:
        kind = obj.get("type")
        if kind == "header":
            _check_header(obj, issues)
        elif kind == "change":
            _check_change(obj, issues, seen_ids)
        elif kind == "bulk":
            _check_bulk(obj, issues)
        elif kind == "aceite":
            _check_accept(obj, issues)
        else:
            issues.append(Issue("error", "L04", f"unknown type {kind!r}", obj["_line"]))
    return issues


def load_log(path: Path | str) -> tuple[Log | None, list[Issue]]:
    """Load and validate a log file. The Log is returned even with errors,
    unless the file has no usable header."""
    text = Path(path).read_text(encoding="utf-8")
    objects, issues = parse_jsonl(text)
    issues.extend(validate_objects(objects))
    headers = [o for o in objects if o.get("type") == "header"]
    if not headers:
        return None, issues
    log = Log(
        header=headers[0],
        changes=[o for o in objects if o.get("type") == "change"],
        bulks=[o for o in objects if o.get("type") == "bulk"],
        lines=objects,
        accepted=[o for o in objects if o.get("type") == "aceite"],
    )
    return log, issues


def has_errors(issues: list[Issue]) -> bool:
    return any(i.severity == "error" for i in issues)
