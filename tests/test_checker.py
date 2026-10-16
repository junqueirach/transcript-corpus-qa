"""Tests for the fidelity checker (WP4), driven by the invented fixtures.

Each folder under fixtures/ holds raw.md, revised.md, log.jsonl and
expected.json. The expectation says whether the case must PASS and which
checks must fire. The adversarial cases (an invented name, a silent deletion,
a fluent wrong word, an altered marker, ...) must all FAIL.
"""
import json
import random
from pathlib import Path

import pytest

from tcqa.checker import run_check
from tcqa.log import load_log
from tcqa.resources import load_lexicon, load_speakers

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
CASES = sorted(p.name for p in FIXTURES.iterdir() if p.is_dir())


def run_fixture(name: str, revised_text: str | None = None):
    d = FIXTURES / name
    raw_bytes = (d / "raw.md").read_bytes()
    log, issues = load_log(d / "log.jsonl")
    revised = revised_text if revised_text is not None else (d / "revised.md").read_text(encoding="utf-8")
    return run_check(raw_bytes.decode("utf-8"), revised, log, issues,
                     lexicon=load_lexicon(FIXTURES / "lexicon.json"),
                     speakers=load_speakers(FIXTURES / "speakers.json"),
                     raw_bytes=raw_bytes)


def expected(name: str) -> dict:
    return json.loads((FIXTURES / name / "expected.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", CASES)
def test_fixture_outcome(name):
    exp = expected(name)
    result = run_fixture(name)
    errors = {f.check for f in result.errors}
    warnings = {f.check for f in result.warnings}
    detail = "\n".join(f"{f.severity} {f.check}: {f.message} [{f.raw}] -> [{f.revised}]" for f in result.findings)
    assert result.passed == exp["pass"], detail
    for check in exp["error_checks"]:
        assert check in errors, f"{name}: expected error {check}\n{detail}"
    for check in exp["warning_checks"]:
        assert check in warnings, f"{name}: expected warning {check}\n{detail}"
    if exp["pass"]:
        assert errors == set(), detail
    if "review_min" in exp:
        assert len(result.review) >= exp["review_min"]


def test_all_spec_cases_are_present():
    required = {"ok_minimal", "ok_markers", "bad_invented_name", "bad_silent_deletion",
                "bad_fluent_swap", "bad_marker_altered", "bad_class", "bad_flags", "bad_speaker",
                "bad_t4_medium", "translation_ok", "translation_bad_paragraphs"}
    assert required <= set(CASES)


def test_ok_minimal_exit_codes():
    result = run_fixture("ok_minimal")
    assert result.exit_code() == 0
    assert result.exit_code(strict=True) == 0


def test_warning_only_exit_code():
    result = run_fixture("ok_speaker_proposed")
    assert result.passed and result.warnings
    assert result.exit_code() == 2
    assert result.exit_code(strict=True) == 1


def test_bad_cases_exit_code_one():
    for name in CASES:
        if name.startswith("bad") or "bad" in name:
            assert run_fixture(name).exit_code() == 1, name


def test_hesitations_are_counted_not_flagged():
    result = run_fixture("ok_minimal")
    st = result.stats
    assert st["unexplained_hunks"] == 0
    assert st["hesitation_words_removed"] >= 3   # eh, e (repeat), né at least
    assert st["explained_hunks"] >= 2            # lexicon fix + T2 fix


def test_review_list_contains_t4_and_suggestions():
    result = run_fixture("ok_t4_high")
    kinds = {(r.get("tier"), r.get("confidence")) for r in result.review if r.get("kind") == "entry"}
    assert ("T4", "high") in kinds
    result = run_fixture("ok_markers")
    assert any(r.get("confidence") == "low" for r in result.review)


# ------------------------------------------------- property-style test (spec item 12)

CONTENT_WORDS = ["farol", "pedra", "noite", "mar", "torre", "silêncio", "verdade", "mestre",
                 "sempre", "nunca", "casa", "luz", "lente", "museu", "degraus", "família"]


@pytest.mark.parametrize("seed", range(25))
def test_random_word_insertion_always_fails(seed):
    """Insert one content word at a random position of a passing revision.
    The checker must flip to FAIL every time."""
    rng = random.Random(seed)
    text = (FIXTURES / "ok_minimal" / "revised.md").read_text(encoding="utf-8")
    head, _, body = text.partition("\n---\n")
    words = body.split(" ")
    pos = rng.randrange(1, len(words))
    word = rng.choice(CONTENT_WORDS)
    mutated = " ".join(words[:pos] + [word] + words[pos:])
    result = run_fixture("ok_minimal", head + "\n---\n" + mutated)
    assert not result.passed, f"seed {seed}: inserted {word!r} at {pos} and the checker still passed"
    assert {"C1", "C6"} & {f.check for f in result.errors}


@pytest.mark.parametrize("seed", range(25))
def test_random_word_deletion_always_fails(seed):
    """Delete one content word (never a filler) from a passing revision."""
    rng = random.Random(seed)
    text = (FIXTURES / "ok_minimal" / "revised.md").read_text(encoding="utf-8")
    head, _, body = text.partition("\n---\n")
    words = body.split(" ")
    candidates = [i for i, w in enumerate(words) if len(w.strip(".,")) > 4]
    pos = rng.choice(candidates)
    mutated = " ".join(words[:pos] + words[pos + 1:])
    result = run_fixture("ok_minimal", head + "\n---\n" + mutated)
    assert not result.passed, f"seed {seed}: deleted {words[pos]!r} and the checker still passed"


@pytest.mark.parametrize("seed", range(25))
def test_random_word_swap_always_fails(seed):
    """Replace one content word by another fluent word (the dangerous case)."""
    rng = random.Random(seed)
    text = (FIXTURES / "ok_minimal" / "revised.md").read_text(encoding="utf-8")
    head, _, body = text.partition("\n---\n")
    words = body.split(" ")
    candidates = [i for i, w in enumerate(words) if w.isalpha() and len(w) > 4]
    pos = rng.choice(candidates)
    words[pos] = rng.choice([w for w in CONTENT_WORDS if w != words[pos].lower()])
    result = run_fixture("ok_minimal", head + "\n---\n" + " ".join(words))
    assert not result.passed, f"seed {seed}: swapped word at {pos} and the checker still passed"


# --- T1 lexicon basis must be backed by the lexicon (C11) -------------------

def _t1(raw, revised, term):
    lex = load_lexicon(FIXTURES / "lexicon.json")
    return lex.supports_t1(term, raw, revised)


def test_t1_lexicon_listed_error_is_supported():
    assert _t1("ponta sirena", "Ponta Serena", "Ponta Serena") is None
    assert _t1("ponta sirena", "Ponta-Serena", "Ponta Serena") is None      # a variant may be written


def test_t1_lexicon_context_words_are_trimmed():
    assert _t1("o farol da ponta sirena", "o Farol da Ponta Serena", "Ponta Serena") is None


def test_t1_lexicon_unlisted_raw_form_is_rejected():
    assert "not a listed error" in _t1("ponta sereia", "Ponta Serena", "Ponta Serena")


def test_t1_lexicon_unknown_term_is_rejected():
    assert "not a term of the lexicon" in _t1("agarmassa", "argamassa", "Argamassa")


def test_t1_lexicon_wrong_revised_is_rejected():
    assert "not 'Ponta Serena'" in _t1("ponta sirena", "Ponta Sereia", "Ponta Serena")


def test_t1_lexicon_observed_errors_count():
    import json, tempfile
    data = {"termos": [{"termo": "Mentalma", "erros_previstos": [], "erros_observados": ["mentala"]}]}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(data, f)
    assert load_lexicon(f.name).supports_t1("Mentalma", "mentala", "Mentalma") is None


def test_t1_lexicon_without_lexicon_is_a_warning():
    d = FIXTURES / "ok_minimal"
    raw_bytes = (d / "raw.md").read_bytes()
    log, issues = load_log(d / "log.jsonl")
    result = run_check(raw_bytes.decode("utf-8"), (d / "revised.md").read_text(encoding="utf-8"), log, issues,
                       speakers=load_speakers(FIXTURES / "speakers.json"), raw_bytes=raw_bytes)
    assert any(f.check == "C11" and "not verified" in f.message for f in result.warnings)
    assert not any(f.check == "C11" for f in result.errors)


# --- repeated spans: each entry is matched where it is (M2) -------------------

def _mini(raw_body, rev_body, changes):
    import json, tempfile
    from tcqa.checker import sha256_bytes
    raw = "Título: t\nQualidade: Bruta\n\n" + raw_body + "\n"
    h = sha256_bytes(raw.encode("utf-8"))
    header = {"type": "header", "file": "r.md", "raw_sha256": h, "idioma": "pt", "falante_nativo": True,
              "derivado_de": None, "versao_revisao": 1, "revisado_em": "2026-10-16", "revisado_por": "t",
              "classe_calculada": "A", "classe_qualidade": "A", "override_motivo": None}
    lines = [header] + [{"type": "change", "id": f"c{i + 1:04d}", "para": 1, "categoria": "termo", "tier": "T2",
                         "confidence": "high", "marker": None, **c} for i, c in enumerate(changes)]
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8") as f:
        f.write("\n".join(json.dumps(x, ensure_ascii=False) for x in lines) + "\n")
    log, issues = load_log(f.name)
    return run_check(raw, rev_body, log, issues)


def test_repeated_raw_span_each_entry_matches_its_own_occurrence():
    raw = "o mestre pestal disse que a escola de pestal era boa e que o método de pestal mudou tudo"
    rev = "O mestre Pestalozzi disse que a escola de Pestalozzi era boa e que o método de Pestalozzi mudou tudo."
    ch = [{"raw": "pestal", "revised": "Pestalozzi", "basis": "context: educador citado"}] * 3
    result = _mini(raw, rev, ch)
    assert not [f for f in result.findings if f.check in ("C1", "C2")], [(f.check, f.message) for f in result.findings]


def test_occurrence_field_selects_the_raw_occurrence():
    raw = "ele falou do pestal e depois do pestal outra vez"
    rev = "Ele falou do pestal e depois do Pestalozzi outra vez."
    result = _mini(raw, rev, [{"raw": "pestal", "revised": "Pestalozzi", "basis": "context: x", "occurrence": 2}])
    assert not [f for f in result.findings if f.check in ("C1", "C2")], [(f.check, f.message) for f in result.findings]
