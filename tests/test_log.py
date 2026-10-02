"""Tests for the structured-log validator (WP3).

Every test builds a small log in memory. All text is invented.
"""
import json

import pytest

from tcqa.log import (Issue, has_errors, load_log, parse_jsonl, split_marker,
                      validate_objects)

SHA = "a" * 64

HEADER = {
    "type": "header", "file": "farol.md", "raw_sha256": SHA, "idioma": "pt",
    "falante_nativo": True, "derivado_de": None, "versao_revisao": 1,
    "revisado_em": "2026-10-02", "revisado_por": "tests",
    "classe_calculada": "B", "classe_qualidade": "B", "override_motivo": None,
    "notas": None,
}


def change(**over):
    base = {
        "type": "change", "id": "c0001", "para": 1,
        "raw": "agarmassa", "revised": "argamassa", "categoria": "termo",
        "tier": "T2", "basis": "context: 'assentadas sem ___' admits one reading",
        "confidence": "high", "marker": None,
    }
    base.update(over)
    return base


def to_text(*objs):
    return "\n".join(json.dumps(o, ensure_ascii=False) for o in objs) + "\n"


def codes(issues):
    return {i.code for i in issues if i.severity == "error"}


def validate(*objs):
    objects, issues = parse_jsonl(to_text(*objs))
    return issues + validate_objects(objects)


# ---------------------------------------------------------------- valid logs

def test_valid_minimal_log_has_no_errors():
    issues = validate(HEADER, change())
    assert not has_errors(issues), issues


def test_valid_marker_entry_with_suggestion():
    entry = change(id="c0002", raw="Tarbaldo Vrzeni",
                   revised="[[? Tarbaldo Vrzeni ⟶ sugestão: Teobaldo Verzeni ]]",
                   categoria="nome", tier="T4", basis="external: 19th-century engineer",
                   confidence="medium", marker="?")
    assert not has_errors(validate(HEADER, entry))


def test_valid_bare_marker_entry():
    entry = change(id="c0003", raw="Tarbaldo Vrzeni", revised="[[?? Tarbaldo Vrzeni ]]",
                   categoria="marcacao", tier=None, basis="name not determinable", confidence=None, marker="??")
    assert not has_errors(validate(HEADER, entry))


def test_valid_bulk_and_deletion_and_insertion():
    bulk = {"type": "bulk", "categoria": "pontuacao", "count": 12}
    deletion = change(id="c0004", raw="[Música]", revised="", categoria="ruido", tier="T1", basis="ASR noise tag")
    insertion = change(id="c0005", raw="", revised="**[Apresentador]**", categoria="falante", tier="T1", basis="generic label")
    assert not has_errors(validate(HEADER, bulk, deletion, insertion))


def test_valid_override_one_step_with_reason():
    header = dict(HEADER, classe_calculada="C", classe_qualidade="B", override_motivo="damage confined to the last minute")
    assert not has_errors(validate(header, change()))


def test_valid_t3_with_paragraph_citation():
    entry = change(id="c0006", tier="T3", basis="crossfile: farol-parte-2.md ¶3 (recap of the same sentence)")
    assert not has_errors(validate(HEADER, entry))


def test_blank_lines_are_ignored():
    text = to_text(HEADER) + "\n\n" + to_text(change())
    objects, issues = parse_jsonl(text)
    assert len(objects) == 2 and not issues


# -------------------------------------------------------------- invalid logs

def test_empty_log_is_an_error():
    assert "L01" in codes(validate())


def test_invalid_json_line_is_reported_with_line_number():
    objects, issues = parse_jsonl(to_text(HEADER) + "{not json}\n")
    assert issues and issues[0].code == "L00" and issues[0].line == 2


def test_header_must_be_first():
    assert "L02" in codes(validate(change(), HEADER))


def test_two_headers_rejected():
    assert "L03" in codes(validate(HEADER, HEADER))


def test_unknown_type_rejected():
    assert "L04" in codes(validate(HEADER, {"type": "comment"}))


def test_header_missing_field():
    header = {k: v for k, v in HEADER.items() if k != "raw_sha256"}
    assert "L10" in codes(validate(header))


def test_bad_sha_and_date_and_version():
    header = dict(HEADER, raw_sha256="xyz", revisado_em="02/10/2026", versao_revisao=0)
    got = codes(validate(header))
    assert {"L11", "L12", "L13"} <= got


def test_override_without_reason_rejected():
    header = dict(HEADER, classe_calculada="C", classe_qualidade="B", override_motivo=None)
    assert "L15" in codes(validate(header))


def test_two_step_override_rejected_even_with_reason():
    header = dict(HEADER, classe_calculada="C", classe_qualidade="A", override_motivo="it reads fine")
    assert "L16" in codes(validate(header))


def test_duplicate_ids_rejected():
    assert "L23" in codes(validate(HEADER, change(), change()))


def test_unknown_field_rejected():
    assert "L21" in codes(validate(HEADER, change(extra="x")))


def test_unknown_category_tier_confidence_marker():
    got = codes(validate(HEADER, change(categoria="typo", tier="T9", confidence="sure", marker="???")))
    assert {"L26", "L27", "L28", "L29"} <= got


def test_marker_entry_must_keep_raw_intact():
    entry = change(raw="Tarbaldo Vrzeni", revised="[[?? Teobaldo Vrzeni ]]", categoria="marcacao", tier=None, confidence=None, marker="??")
    assert "L32" in codes(validate(HEADER, entry))


def test_marker_entry_kind_mismatch():
    entry = change(raw="x y", revised="[[?? x y ]]", categoria="marcacao", tier=None, confidence=None, marker="?")
    assert "L31" in codes(validate(HEADER, entry))


def test_marker_entry_not_a_marker():
    entry = change(raw="x y", revised="x y", categoria="marcacao", tier=None, confidence=None, marker="?")
    assert "L30" in codes(validate(HEADER, entry))


def test_marker_with_high_confidence_rejected():
    entry = change(raw="x", revised="[[? x ⟶ sugestão: y ]]", categoria="nome", tier="T4", basis="external: z", confidence="high", marker="?")
    assert "L33" in codes(validate(HEADER, entry))


def test_suggestion_without_confidence_rejected():
    entry = change(raw="x", revised="[[? x ⟶ sugestão: y ]]", categoria="marcacao", tier=None, confidence=None, marker="?")
    assert "L34" in codes(validate(HEADER, entry))


def test_medium_confidence_written_into_text_rejected():
    """The core rule: medium/low never changes the text."""
    assert "L39" in codes(validate(HEADER, change(confidence="medium")))


def test_change_without_tier_rejected():
    assert "L38" in codes(validate(HEADER, change(tier=None)))


def test_change_without_basis_rejected():
    assert "L40" in codes(validate(HEADER, change(basis="")))


def test_t3_requires_crossfile_basis_with_paragraph():
    assert "L41" in codes(validate(HEADER, change(tier="T3", basis="context: looks the same")))
    assert "L42" in codes(validate(HEADER, change(tier="T3", basis="crossfile: other.md")))


def test_t4_requires_external_basis():
    assert "L41" in codes(validate(HEADER, change(tier="T4", basis="context: famous")))


def test_t2_requires_context_basis():
    assert "L41" in codes(validate(HEADER, change(tier="T2", basis="obvious")))


def test_empty_raw_needs_insertion_category():
    assert "L35" in codes(validate(HEADER, change(raw="", categoria="sentido")))


def test_empty_revised_needs_removal_category():
    assert "L36" in codes(validate(HEADER, change(revised="", categoria="sentido")))


def test_falante_novo_requires_name_and_quote():
    entry = change(raw="", revised="**[Ana]**", categoria="falante", tier="T2",
                   basis="context: self-identification", falante_novo={"nome": "Ana"})
    assert "L43" in codes(validate(HEADER, entry))


def test_falante_novo_on_other_category_rejected():
    entry = change(falante_novo={"nome": "Ana", "citacao": "eu sou a Ana"})
    assert "L44" in codes(validate(HEADER, entry))


def test_bulk_rules():
    got = codes(validate(HEADER, {"type": "bulk", "categoria": "sentido", "count": -1, "x": 1}))
    assert {"L50", "L51", "L52"} <= got


# ------------------------------------------------------------------ helpers

@pytest.mark.parametrize("text, expected", [
    ("[[? abc ]]", ("?", "abc", None)),
    ("[[?? a b c ]]", ("??", "a b c", None)),
    ("[[? abc ⟶ sugestão: xyz ]]", ("?", "abc", "xyz")),
    ("[[? abc ⟶ suggestion: xyz ]]", ("?", "abc", "xyz")),
    ("abc", None),
    ("[[? abc ]] tail", None),
])
def test_split_marker(text, expected):
    assert split_marker(text) == expected


def test_load_log_from_file(tmp_path):
    p = tmp_path / "x.log.jsonl"
    p.write_text(to_text(HEADER, change()), encoding="utf-8")
    log, issues = load_log(p)
    assert log is not None and not has_errors(issues)
    assert log.header["file"] == "farol.md" and len(log.changes) == 1


def test_load_log_without_header_returns_none(tmp_path):
    p = tmp_path / "x.log.jsonl"
    p.write_text(to_text(change()), encoding="utf-8")
    log, issues = load_log(p)
    assert log is None and has_errors(issues)
