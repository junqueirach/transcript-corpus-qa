"""Tests for the v2 commands: lexicon, draft-log, review, export, metrics, index summary.
Built on the public demo (invented text)."""
import json
import shutil
from pathlib import Path

from tcqa.cli import main
from tcqa.draftlog import draft
from tcqa.lexicon_tools import lexicon_hits, merge, validate
from tcqa.log import load_log
from tcqa.resources import load_lexicon

REPO = Path(__file__).resolve().parent.parent
DEMO = REPO / "examples" / "demo"


def _lex():
    return json.loads((DEMO / "lexicon.json").read_text(encoding="utf-8"))


def test_hits_finds_lexicon_errors_in_the_raw():
    result = lexicon_hits((DEMO / "raw.md").read_text(encoding="utf-8"), _lex())
    terms = {h["termo"] for h in result["hits"]}
    assert "Ponta Serena" in terms


def test_validate_flags_ambiguous_and_common_word_errors():
    data = {"termos": [{"termo": "Khaos", "erros_previstos": ["Caos"]}, {"termo": "Caos"},
                       {"termo": "Antares", "erros_previstos": ["antes"]}]}
    problems = " | ".join(validate(data))
    assert "is another term" in problems and "common word" in problems


def test_merge_unions_forms():
    a = {"termos": [{"termo": "X", "erros_previstos": ["a"]}]}
    b = {"termos": [{"termo": "X", "erros_previstos": ["b"]}, {"termo": "Y"}]}
    m = merge([a, b])
    x = next(e for e in m["termos"] if e["termo"] == "X")
    assert x["erros_previstos"] == ["a", "b"] and len(m["termos"]) == 2


def test_draft_log_stubs_and_lexicon_prefill_then_completed_log_passes(tmp_path):
    lines = draft((DEMO / "raw.md").read_text(encoding="utf-8"), (DEMO / "revised_good.md").read_text(encoding="utf-8"),
                  None, load_lexicon(DEMO / "lexicon.json"), revised_name="revised_good.md")
    by_raw = {l.get("raw"): l for l in lines if l.get("type") == "change"}
    assert by_raw["ponta sirena"]["tier"] == "T1" and by_raw["ponta sirena"]["basis"] == "lexicon:Ponta Serena"
    assert by_raw["tarbaldo vrzeni"]["marker"] == "??" and by_raw["tarbaldo vrzeni"]["basis"].startswith("TODO")
    # an unfilled draft fails the check
    log = tmp_path / "draft.jsonl"
    log.write_text("\n".join(json.dumps(l, ensure_ascii=False) for l in lines) + "\n", encoding="utf-8")
    args = [str(DEMO / "raw.md"), str(DEMO / "revised_good.md"), str(log), "--lexicon", str(DEMO / "lexicon.json")]
    assert main(["check", *args]) == 1
    # the reviser completes the stubs → pass
    for l in lines:
        if str(l.get("basis", "")).startswith("TODO"):
            if l["marker"]:
                l["basis"] = "proper name destroyed by the ASR"
            else:
                l.update({"tier": "T2", "basis": "context: 'laid without any ___' admits one reading", "confidence": "high"})
    log.write_text("\n".join(json.dumps(l, ensure_ascii=False) for l in lines) + "\n", encoding="utf-8")
    assert main(["check", *args]) == 0


def _copy_run(tmp_path):
    """A run folder in the user layout: revised file + _auditoria/<name>.log.jsonl."""
    run = tmp_path / "run"
    (run / "_auditoria").mkdir(parents=True)
    shutil.copy(DEMO / "revised_good.md", run / "talk [Revisado].md")
    lines = [json.loads(x) for x in (DEMO / "log_good.jsonl").read_text(encoding="utf-8").splitlines()]
    lines[0]["file"] = "talk [Revisado].md"
    # one suggestion and one T4 correction to review
    lines.append({"type": "change", "id": "c0009", "para": 3, "raw": "whale oil", "revised": "[[? whale oil ⟶ sugestão: whale-oil ]]",
                  "categoria": "marcacao", "tier": None, "basis": "hyphenation unsure", "confidence": "medium", "marker": "?"})
    (run / "_auditoria" / "talk [Revisado].log.jsonl").write_text(
        "\n".join(json.dumps(l, ensure_ascii=False) for l in lines) + "\n", encoding="utf-8")
    return run


def test_review_build_groups_and_apply_rejects_marker_suggestion(tmp_path):
    run = _copy_run(tmp_path)
    assert main(["review", "build", str(run)]) == 0
    queue = json.loads((run / "revisao_humana.json").read_text(encoding="utf-8"))
    kinds = {r["tipo"] for r in queue["itens"]}
    assert "sugestao" in kinds
    for r in queue["itens"]:
        r["decisao"] = "rejeitar"
    (run / "revisao_humana.json").write_text(json.dumps(queue, ensure_ascii=False), encoding="utf-8")
    assert main(["review", "apply", str(run / "revisao_humana.json")]) == 0
    log, _ = load_log(run / "_auditoria" / "talk [Revisado].log.jsonl")
    assert any("rejected" in str(e.get("notas", "")) for e in log.changes)
    assert log.header["versao_revisao"] == 2


def test_export_chunks_carry_metadata_and_skip_non_content(tmp_path):
    from tcqa.export import chunks_for
    from tcqa.frontmatter import join_document, split_document
    fm, body, _ = split_document((DEMO / "revised_good.md").read_text(encoding="utf-8"))
    fm = dict(fm)
    fm["segmentos_nao_conteudo"] = ["1:anuncio"]
    path = tmp_path / "t.md"
    path.write_text(join_document(fm, body), encoding="utf-8")
    chunks = chunks_for(path, tmp_path, lexicon=load_lexicon(DEMO / "lexicon.json"), categories={})
    assert chunks and all(c["tipo_segmento"] == "conteudo" for c in chunks)
    assert all(c["paragrafos"][0] != 1 for c in chunks)
    assert any("Island of Gulls" in c["termos"] for c in chunks)
    with_ads = chunks_for(path, tmp_path, include_non_content=True)
    assert any(c["tipo_segmento"] == "anuncio" for c in with_ads)
    assert {"fonte_url", "falante", "classe", "id", "texto"} <= set(chunks[0])


def test_metrics_and_index_summary(tmp_path):
    run = _copy_run(tmp_path)
    out = tmp_path / "m.csv"
    assert main(["metrics", str(run), "--csv", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    assert "TOTAL" in text and "revisao_por_mil" in text
    assert main(["index", "summary", str(run), "--out", str(tmp_path / "s.md")]) == 0
    assert "| **total** | 1 |" in (tmp_path / "s.md").read_text(encoding="utf-8")


def test_agent_templates_carry_no_personal_paths():
    for path in (REPO / "agent").rglob("*.md"):
        text = path.read_text(encoding="utf-8")
        assert "C:\\Users" not in text and "D:\\transcript" not in text, path
        assert "\r" not in text, path


def test_agent_install_renders_placeholders(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("install", REPO / "agent" / "install.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main(["--claude-home", str(tmp_path)]) == 0
    skill = (tmp_path / "skills" / "tcqa" / "SKILL.md").read_text(encoding="utf-8")
    assert "{TCQA_REPO}" not in skill and str(REPO) in skill
    assert mod.main(["--claude-home", str(tmp_path), "--check"]) == 0


def test_draft_log_hashes_raw_bytes_and_does_not_duplicate_widened_spans(tmp_path):
    from tcqa.checker import sha256_bytes
    raw = "Título: t\r\nQualidade: Bruta\r\n\r\ne o joão val elan falou\r\n".encode("utf-8")   # CRLF on disk
    (tmp_path / "raw.md").write_bytes(raw)
    (tmp_path / "rev.md").write_text("---\ntitulo: t\nidioma: pt\n---\n\nE o Jan Val Ellam falou.\n", encoding="utf-8", newline="\n")
    (tmp_path / "lex.json").write_text(json.dumps({"termos": [{"termo": "Jan Val Ellam", "erros_previstos": ["joão val elan"]}]}), encoding="utf-8")
    out = tmp_path / "log.jsonl"
    assert main(["draft-log", str(tmp_path / "raw.md"), str(tmp_path / "rev.md"), "--lexicon", str(tmp_path / "lex.json"), "--out", str(out)]) == 0
    lines = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
    assert lines[0]["raw_sha256"] == sha256_bytes(raw)
    changes = [l for l in lines if l.get("type") == "change"]
    assert len(changes) == 1 and changes[0]["raw"] == "joão val elan" and changes[0]["tier"] == "T1"


def test_classify_log_sets_termos_corrigidos_and_syncs_header(tmp_path):
    shutil.copy(DEMO / "revised_good.md", tmp_path / "r.md")
    shutil.copy(DEMO / "log_good.jsonl", tmp_path / "l.jsonl")
    text = (tmp_path / "r.md").read_text(encoding="utf-8").replace("termos_corrigidos: 1", "termos_corrigidos: 0")
    (tmp_path / "r.md").write_text(text, encoding="utf-8", newline="\n")
    assert main(["classify", str(tmp_path / "r.md"), "--write", "--log", str(tmp_path / "l.jsonl")]) == 0
    assert "termos_corrigidos: 1" in (tmp_path / "r.md").read_text(encoding="utf-8")
    head = json.loads((tmp_path / "l.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert head["classe_calculada"] == "B" and head["idioma"] == "en"


def test_corpus_frequency_flags_common_error_forms(tmp_path):
    from tcqa.lexicon_tools import corpus_common_forms
    data = {"termos": [{"termo": "Vega", "erros_previstos": ["veja"]}, {"termo": "Ponta Serena", "erros_previstos": ["ponta sirena"]}]}
    raws = []
    for i in range(4):
        p = tmp_path / f"r{i}.md"
        p.write_text("Título: t\n\nveja bem " + ("o farol da ponta sirena" if i == 0 else "nada") + "\n", encoding="utf-8")
        raws.append(p)
    flagged = " ".join(corpus_common_forms(data, raws, 0.5))
    assert "'veja'" in flagged and "ponta sirena" not in flagged
