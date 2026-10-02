"""Unit tests for front matter, text analysis, language detection, fillers
and classification. All text invented."""
import pytest

from tcqa import classify as cls
from tcqa.frontmatter import (FrontmatterError, dump_frontmatter, join_document,
                              parse_value, split_document)
from tcqa.hesitations import filler_keys, is_filler_run
from tcqa.language import detect_language, language_matches
from tcqa.textnorm import analyze, analyze_body, find_subsequence, keys_of, normalize_word

ARROW = "⟶"


# ------------------------------------------------------------- front matter

def test_frontmatter_roundtrip():
    data = {"titulo": "Farol: a história", "n": 3, "pct": 1.5, "ok": True, "nada": None,
            "lista": ["a b", "c"], "texto": "has # hash and \"quotes\""}
    text = dump_frontmatter(data) + "\nbody\n"
    fm, body, kind = split_document(text)
    assert kind == "yaml" and fm == data and body == "body\n"


@pytest.mark.parametrize("raw, value", [
    ("null", None), ("~", None), ("true", True), ("false", False), ("12", 12), ("1.5", 1.5),
    ('"x: y"', "x: y"), ("'a'", "a"), ("plain words", "plain words"), ("[]", []),
    ("[1, \"a, b\", c]", [1, "a, b", "c"]),
])
def test_parse_value(raw, value):
    assert parse_value(raw) == value


def test_comment_after_value_is_ignored():
    fm, _, _ = split_document("---\nclasse: \"C\"   # A | B | C\nurl: \"http://x/#frag\"\n---\n")
    assert fm == {"classe": "C", "url": "http://x/#frag"}


def test_nested_block_rejected():
    with pytest.raises(FrontmatterError):
        split_document("---\nmeta:\n  a: 1\n---\n")


def test_unclosed_frontmatter_rejected():
    with pytest.raises(FrontmatterError):
        split_document("---\na: 1\nbody")


def test_legacy_header_is_split_from_body():
    fm, body, kind = split_document("Título: Farol\nAutor: X\nQualidade: Bruta\n\ntexto do corpo\n")
    assert kind == "legacy" and fm["Título"] == "Farol" and body == "texto do corpo\n"


def test_no_header_means_everything_is_body():
    fm, body, kind = split_document("apenas texto\nmais texto\n")
    assert kind == "none" and fm is None and body.startswith("apenas")


def test_bom_tolerated():
    fm, _, kind = split_document("﻿---\na: 1\n---\n")
    assert kind == "yaml" and fm == {"a": 1}


# -------------------------------------------------------------- text model

def test_paragraphs_notes_speakers_markers_tokens():
    body = ("**[Apresentador]** Boa noite, [t=00:12] a todos.\n\n"
            "> **[nota de revisão]** nada aqui conta como texto.\n\n"
            f"O engenheiro [[?? tarbaldo vrzeni ]] veio da ilha. [[? óleo {ARROW} sugestão: óleo de baleia ]]\n")
    doc = analyze_body(body)
    assert [p.kind for p in doc.paragraphs] == ["text", "note", "text"]
    assert doc.speakers == [(1, "Apresentador")]
    assert [m.kind for m in doc.markers] == ["??", "?"]
    assert doc.markers[1].original == "óleo" and doc.markers[1].suggestion == "óleo de baleia"
    words = [t.text for t in doc.tokens]
    assert words == ["Boa", "noite", "a", "todos", "O", "engenheiro", "tarbaldo", "vrzeni", "veio", "da", "ilha", "óleo"]
    assert [t.marker for t in doc.tokens if t.text in ("tarbaldo", "vrzeni", "óleo")] == ["??", "??", "?"]
    assert doc.count_markers("??") == 1 and doc.words_in_markers("??") == 2


def test_quote_block_that_is_not_a_note_is_a_problem():
    doc = analyze_body("> citação qualquer\n")
    assert doc.problems


def test_marker_crossing_paragraphs_is_a_problem():
    doc = analyze_body("[[?? primeira linha\n\nsegunda linha ]]\n")
    assert any("crosses" in p for p in doc.problems)


def test_normalize_word_and_keys():
    assert normalize_word("Óleo") == ("óleo", "oleo")
    assert keys_of(f"**[X]** [[? Ponta Serena {ARROW} sugestão: outra ]] [t=01:00] já") == ["ponta", "serena", "ja"]


def test_find_subsequence():
    assert find_subsequence(list("abcabc"), list("bc")) == [1, 4]
    assert find_subsequence(list("abc"), []) == []


def test_analyze_full_document_with_yaml():
    doc = analyze("---\nidioma: pt\n---\n\nTexto simples.\n")
    assert doc.header_kind == "yaml" and doc.frontmatter == {"idioma": "pt"} and len(doc.tokens) == 2


# ---------------------------------------------------------------- language

PT = ("o farol foi construído pelo engenheiro que veio da ilha e as pedras foram assentadas sem argamassa "
      "mas mesmo assim resistiram a três tempestades e o faroleiro vivia com a família numa casa ao lado da torre "
      "e subia os degraus todas as noites para acender a luz que os pescadores viam de longe quando o mar estava bravo")
EN = ("the lighthouse was built by an engineer who came from the island and the stones were laid without mortar "
      "but they still withstood three storms and the keeper lived with his family in a house beside the tower "
      "and he climbed the steps every night to light the lamp that the fishermen could see from far away when it was rough")


def test_detect_portuguese_and_english():
    assert detect_language(PT)[0] == "pt"
    assert detect_language(EN)[0] == "en"


def test_detect_returns_none_on_short_or_mixed_text():
    assert detect_language("farol torre pedra")[0] is None
    assert detect_language("xq zv kk " * 40)[0] is None


def test_language_matches_region_codes():
    assert language_matches("pt-BR", "pt") and not language_matches("en", "pt") and not language_matches(None, "pt")


# ----------------------------------------------------------------- fillers

def test_filler_keys_per_language():
    assert "ne" in filler_keys("pt-BR") and "um" in filler_keys("en") and "musica" in filler_keys("en")
    assert "like" not in filler_keys("en") and "entao" not in filler_keys("pt")


def test_filler_run_accepts_repeats_and_fillers_only():
    assert is_filler_run(["eh", "ne"], None, None, "pt")
    assert is_filler_run(["o", "o"], "o", None, "pt")       # 'o o o' -> 'o', first kept
    assert is_filler_run(["o", "o"], None, "o", "pt")       # last kept
    assert not is_filler_run(["farol"], None, None, "pt")
    assert not is_filler_run([], None, None, "pt")


# ---------------------------------------------------------- classification

def doc_with(bad_words: int, total: int, paragraphs: int = 4):
    per = total // paragraphs
    paras = [" ".join(["palavra"] * per) for _ in range(paragraphs)]
    if bad_words:
        paras[-1] = "[[?? " + " ".join(["ruim"] * bad_words) + " ]] " + " ".join(["palavra"] * (per - bad_words))
    return analyze_body("\n\n".join(paras) + "\n")


def test_class_thresholds():
    assert cls.class_from_pct(0) == "A"
    assert cls.class_from_pct(cls.CLASS_B_MAX_PCT) == "B"
    assert cls.class_from_pct(cls.CLASS_B_MAX_PCT + 0.01) == "C"


def test_compute_counts_and_class():
    c = cls.compute(doc_with(0, 400))
    assert (c.classe_calculada, c.pct_irrecuperavel, c.apto_finetuning, c.apto_rag) == ("A", 0.0, True, True)
    c = cls.compute(doc_with(4, 400))     # 1 %
    assert c.classe_calculada == "B" and c.apto_finetuning
    c = cls.compute(doc_with(40, 400), )  # 10 % in one paragraph of 25 % -> section rule -> B
    assert c.classe_calculada == "B" and c.secao_degradada == "§4"


def test_section_rule_does_not_rescue_spread_damage():
    body = "\n\n".join("[[?? ruim ruim ]] " + " ".join(["palavra"] * 18) for _ in range(5)) + "\n"
    c = cls.compute(analyze_body(body))   # 10 % spread over every paragraph
    assert c.classe_calculada == "C" and c.secao_degradada is None and not c.apto_finetuning


def test_derived_file_is_never_finetune_ready():
    assert cls.compute(doc_with(0, 400), derived=True).apto_finetuning is False


def test_language_scope_for_finetuning():
    assert cls.compute(doc_with(0, 400), language="en", finetune_languages={"pt-BR"}).apto_finetuning is False
    assert cls.compute(doc_with(0, 400), language="pt-BR", finetune_languages={"pt"}).apto_finetuning is True


def test_unreadable_file_not_rag_ready():
    body = "[[?? " + " ".join(["x"] * 60) + " ]] " + " ".join(["y"] * 40)
    assert cls.compute(analyze_body(body)).apto_rag is False


def test_override_rules():
    assert cls.override_ok("B", "B", None)[0]
    assert cls.override_ok("C", "B", "damage confined to one minute")[0]
    assert not cls.override_ok("C", "B", None)[0]
    assert not cls.override_ok("C", "A", "reads fine")[0]
