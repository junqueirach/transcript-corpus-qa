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
