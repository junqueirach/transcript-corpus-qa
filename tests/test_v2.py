"""Tests for the v2 checker rules: speaker names as lexicon, homophony, accepted
warnings, falantes vs labels, main-author participation, non-content segments,
book citations (T3 'obra:'), occurrence. All text is invented."""
import json
import tempfile
from pathlib import Path

from tcqa.checker import run_check, sha256_bytes
from tcqa.classify import compute
from tcqa.frontmatter import join_document
from tcqa.log import load_log, validate_objects
from tcqa.resources import load_lexicon, load_speakers
from tcqa.textnorm import analyze_body

RAW_HEAD = "Título: t\nQualidade: Bruta\n\n"


def _tmp(data, suffix):
    with tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False, encoding="utf-8", newline="\n") as f:
        if suffix == ".json":
            json.dump(data, f, ensure_ascii=False)
        else:
            f.write(data)
    return f.name


def run(raw_body, rev_body, changes=(), extra_lines=(), fm_extra=None, lexicon=None, speakers=None):
    raw = RAW_HEAD + raw_body + "\n"
    h = sha256_bytes(raw.encode("utf-8"))
    comp = compute(analyze_body(rev_body), language="pt")
    fm = {"titulo": "t", "idioma": "pt", "derivado_de": None, "qualidade": "Revisão 1", "raw_sha256": h,
          "revisado_em": "2026-10-16", "versao_revisao": 1, **comp.as_frontmatter(),
          "classe_qualidade": comp.classe_calculada, "override_motivo": None}
    fm.update(fm_extra or {})
    revised = join_document(fm, "\n" + rev_body + "\n")
    header = {"type": "header", "file": "r.md", "raw_sha256": h, "idioma": "pt", "falante_nativo": True,
              "derivado_de": None, "versao_revisao": 1, "revisado_em": "2026-10-16", "revisado_por": "t",
              "classe_calculada": comp.classe_calculada, "classe_qualidade": comp.classe_calculada, "override_motivo": None}
    lines = [header] + [{"type": "change", "id": f"c{i + 1:04d}", "para": 1, "categoria": "termo",
                         "confidence": "high", "marker": None, **c} for i, c in enumerate(changes)] + list(extra_lines)
    log, issues = load_log(_tmp("\n".join(json.dumps(x, ensure_ascii=False) for x in lines) + "\n", ".jsonl"))
    return run_check(raw, revised, log, issues, raw_bytes=raw.encode("utf-8"),
                     lexicon=load_lexicon(_tmp(lexicon, ".json")) if lexicon else None,
                     speakers=load_speakers(_tmp(speakers, ".json")) if speakers else None)


def codes(result, severity):
    return [(f.check, f.message) for f in result.findings if f.severity == severity]


LEX = {"termos": [{"termo": "Caos", "risco_homofonia": "alto", "erros_previstos": ["cãos"]},
                  {"termo": "Mentalma", "erros_previstos": ["mental ma"]}]}
SPK = {"_rotulos_genericos": ["Entrevistador"],
       "autor_principal": {"nome_canonico": "Narrador Inventado", "variantes_de_transcricao": ["narrador inventad"]}}


def test_speaker_registry_forms_back_a_t1_fix():
    r = run("e o narrador inventad falou", "E o Narrador Inventado falou.",
            [{"raw": "narrador inventad", "revised": "Narrador Inventado", "tier": "T1", "basis": "lexicon:Narrador Inventado"}],
            lexicon=LEX, speakers=SPK)
    assert not [c for c in codes(r, "error") if c[0] == "C11"], codes(r, "error")


def test_high_homophony_t1_fix_is_a_warning_and_review_item():
    r = run("no começo era o cãos", "No começo era o Caos.",
            [{"raw": "cãos", "revised": "Caos", "tier": "T1", "basis": "lexicon:Caos"}], lexicon=LEX)
    assert any(c[0] == "C11" and "homophony" in c[1] for c in codes(r, "warning"))
    assert any(x.get("why") == "homofonia" for x in r.review)
    assert r.passed


def test_accepted_warning_becomes_info_and_unknown_acceptance_warns():
    args = dict(raw_body="no começo era o cãos", rev_body="No começo era o Caos.",
                changes=[{"raw": "cãos", "revised": "Caos", "tier": "T1", "basis": "lexicon:Caos"}], lexicon=LEX)
    r = run(**args, extra_lines=[{"type": "aceite", "code": "C11", "motivo": "a frase fala do Caos primordial"}])
    assert not [c for c in codes(r, "warning") if c[0] == "C11"]
    assert any("accepted" in f.message for f in r.findings if f.severity == "info")
    r2 = run(**args, extra_lines=[{"type": "aceite", "code": "C5", "motivo": "x"}])
    assert any(c[0] == "C0" and "matches no warning" in c[1] for c in codes(r2, "warning"))


def test_aceite_validation():
    issues = validate_objects([{"type": "header", "_line": 1}, {"type": "aceite", "code": "X", "_line": 2}])
    assert {"L60", "L61"} <= {i.code for i in issues}


def test_falantes_must_match_labels():
    body = "**[Entrevistador]** Boa noite.\n\n**[Narrador Inventado]** Boa noite a todos."
    r = run("boa noite boa noite a todos", body, speakers=SPK,
            fm_extra={"falantes": ["Entrevistador", "Outra Pessoa"]})
    msgs = [m for c, m in codes(r, "warning") if c == "C10"]
    assert any("not listed in 'falantes'" in m for m in msgs)
    assert any("labels no turn" in m for m in msgs)


def test_main_author_participation_flag():
    body = "**[Entrevistador]** Boa noite.\n\n**[Narrador Inventado]** Boa noite a todos."
    base = dict(raw_body="boa noite boa noite a todos", rev_body=body, speakers=SPK)
    fm = {"falantes": ["Entrevistador", "Narrador Inventado"], "autor_principal": "Narrador Inventado"}
    r = run(**base, fm_extra={**fm, "autor_principal_participa": False})
    assert any(c == "C10" and "participa is false" in m for c, m in codes(r, "error"))
    r = run(**base, fm_extra={**fm, "autor_principal_participa": True})
    assert not [m for c, m in codes(r, "error") + codes(r, "warning") if "participa" in m]


def test_non_content_segments_are_validated_and_counted():
    body = "Compre o curso agora.\n\nO farol foi construído em pedra."
    raw = "compre o curso agora o farol foi construído em pedra"
    ok = run(raw, body, fm_extra={"segmentos_nao_conteudo": ["1:anuncio"], "pct_nao_conteudo": 40.0})
    assert ok.passed, codes(ok, "error")
    bad = run(raw, body, fm_extra={"segmentos_nao_conteudo": ["1-5:propaganda"], "pct_nao_conteudo": 10.0})
    msgs = [m for c, m in codes(bad, "error") if c == "C7"]
    assert any("does not exist" in m for m in msgs) and any("tipo" in m for m in msgs) and any("pct_nao_conteudo" in m for m in msgs)


def test_t3_book_citation():
    def issues(basis):
        obj = {"type": "change", "id": "c0001", "para": 1, "raw": "a", "revised": "b", "categoria": "termo",
               "tier": "T3", "basis": basis, "confidence": "high", "marker": None, "_line": 2}
        return {i.code for i in validate_objects([{"type": "header", "_line": 1}, obj])}
    assert not {"L41", "L42"} & issues("obra: Livro Inventado, p. 45")
    assert not {"L41", "L42"} & issues("obra: Livro Inventado, cap. 3")
    assert "L42" in issues("obra: Livro Inventado")
    assert not {"L41", "L42"} & issues("crossfile: outra.md ¶12")
    assert "L41" in issues("livro: x p. 3")


def test_occurrence_must_be_positive_int():
    obj = {"type": "change", "id": "c0001", "para": 1, "raw": "a", "revised": "b", "categoria": "termo", "tier": "T2",
           "basis": "context: x", "confidence": "high", "marker": None, "occurrence": 0, "_line": 2}
    assert "L45" in {i.code for i in validate_objects([{"type": "header", "_line": 1}, obj])}


def test_classify_write_normalises_language_and_fills_non_content_share(tmp_path):
    from tcqa.cli import main
    body = "Compre o curso agora.\n\nO farol foi construído em pedra."
    path = tmp_path / "r.md"
    path.write_text(join_document({"titulo": "t", "idioma": "pt-BR", "derivado_de": None,
                                   "segmentos_nao_conteudo": ["1:anuncio"]}, "\n" + body + "\n"),
                    encoding="utf-8", newline="\n")
    assert main(["classify", str(path), "--write"]) == 0
    text = path.read_text(encoding="utf-8")
    assert "idioma: pt\n" in text and "pct_nao_conteudo: 40.0" in text
    assert "\r" not in Path(path).read_bytes().decode("utf-8")
