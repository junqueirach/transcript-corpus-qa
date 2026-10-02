"""Tests for backup, index, summarize and the command-line entry point (WP5)."""
import csv
import json
import shutil
from pathlib import Path

import pytest

from tcqa.backup import backup_file, next_free_name, sha256_file
from tcqa.cli import main
from tcqa.index import (audit_index, build_rows, normalise_duration, read_index,
                        sanitize_filename, write_index)
from tcqa.log import load_log
from tcqa.summarize import render_summary

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


# ----------------------------------------------------------------- backup

def test_backup_mirrors_subfolder_and_never_overwrites(tmp_path):
    root = tmp_path / "corpus"
    src = root / "canal" / "talk.md"
    src.parent.mkdir(parents=True)
    src.write_text("versão 1", encoding="utf-8")
    bk = tmp_path / "backup"
    dest1, sha1 = backup_file(src, root, bk)
    assert dest1 == bk / "canal" / "talk.md" and dest1.read_text(encoding="utf-8") == "versão 1"
    assert sha1 == sha256_file(src)
    src.write_text("versão 2", encoding="utf-8")
    dest2, _ = backup_file(src, root, bk)
    dest3, _ = backup_file(src, root, bk)
    assert dest2.name == "talk_001.md" and dest3.name == "talk_002.md"
    assert dest1.read_text(encoding="utf-8") == "versão 1"   # first copy untouched


def test_backup_outside_root_uses_plain_name(tmp_path):
    src = tmp_path / "elsewhere" / "x.md"
    src.parent.mkdir()
    src.write_text("x", encoding="utf-8")
    dest, _ = backup_file(src, tmp_path / "root", tmp_path / "bk")
    assert dest == tmp_path / "bk" / "x.md"


def test_backup_dry_run_copies_nothing(tmp_path):
    src = tmp_path / "x.md"
    src.write_text("x", encoding="utf-8")
    dest, _ = backup_file(src, tmp_path, tmp_path / "bk", dry_run=True)
    assert not dest.exists()


def test_next_free_name(tmp_path):
    (tmp_path / "a.md").write_text("", encoding="utf-8")
    (tmp_path / "a_001.md").write_text("", encoding="utf-8")
    assert next_free_name(tmp_path, "a.md").name == "a_002.md"
    assert next_free_name(tmp_path, "b.md").name == "b.md"


def test_backup_cli(tmp_path, capsys):
    src = tmp_path / "raw.md"
    src.write_text("abc", encoding="utf-8")
    code = main(["backup", str(src), "--backup-dir", str(tmp_path / "bk"), "--root", str(tmp_path)])
    assert code == 0 and (tmp_path / "bk" / "raw.md").exists()
    assert sha256_file(src) in capsys.readouterr().out


# ------------------------------------------------------------------ index

@pytest.mark.parametrize("raw, expected", [
    ("9:10", "00:09:10"), ("06:45", "00:06:45"), ("2:19:23", "02:19:23"), ("3:08:13", "03:08:13"),
    ("00:09:10", "00:09:10"), ("abc", None), ("", None), (None, None), ("1:75", None),
])
def test_normalise_duration(raw, expected):
    assert normalise_duration(raw) == expected


def test_sanitize_filename():
    assert sanitize_filename("Seminar Official Contact / Norse Mythology") == "Seminar Official Contact - Norse Mythology"
    assert sanitize_filename("A  B   C") == "A B C"
    assert sanitize_filename('Who: "what"?') == "Who what"
    assert sanitize_filename("Ends with dot.") == "Ends with dot"


def _old_style_rows():
    base = {"pasta": "Serie X", "tipo": "Palestra", "canal": "Canal A", "data": "2020", "duracao": "9:10",
            "classe_qualidade": "A", "falantes": "Autor", "trechos_incertos": "0", "trechos_irrecuperaveis": "0",
            "apto_rag": "true", "apto_finetuning": "false", "audio_recuperavel": "true", "revisado_em": "2026-07-31"}
    en = dict(base, arquivo="01 - INTRO.md", titulo="01 - INTRO")
    pt = dict(base, arquivo="01 - INTRO (PT-BR).md", titulo="01 - INTRO", apto_finetuning="true")
    odd = dict(base, arquivo="Seminar AB.md", titulo="Seminar A/B", canal="Canal B", classe_qualidade="C", apto_finetuning="true",
               duracao="3:07:50")
    dbl = dict(base, arquivo="09 - X -  part II.md", titulo="09 - X - part II", duracao="00:23:13")
    return [en, pt, odd, dbl]


def test_audit_finds_each_known_inconsistency():
    findings = "\n".join(audit_index(_old_style_rows()))
    assert "column 'idioma' is missing" in findings
    assert "duration '9:10' is not HH:MM:SS" in findings
    assert "looks like a translation but has no derivado_de link" in findings
    assert "translation marked apto_finetuning=true" in findings
    assert "class A source file with apto_finetuning=false" in findings
    assert "class C with apto_finetuning=true" in findings
    assert "several channel names" in findings
    assert "double space in file name" in findings
    assert "title contains '/'" in findings
    assert "cannot be verified from this index" in findings


def test_audit_clean_new_format_index_has_no_findings(tmp_path):
    # build an index from the fixtures' ok cases and audit it
    folder = tmp_path / "corpus"
    for case in ("ok_minimal", "ok_markers"):
        (folder / case).mkdir(parents=True)
        shutil.copy(FIXTURES / case / "revised.md", folder / case / f"{case}.md")
    rows, problems = build_rows(folder)
    assert len(rows) == 2 and not problems
    by_name = {r["arquivo"]: r for r in rows}
    assert by_name["ok_minimal.md"]["duracao"] == "00:03:10" and by_name["ok_minimal.md"]["classe_calculada"] == "A"
    assert by_name["ok_markers.md"]["classe_calculada"] == "B" and by_name["ok_markers.md"]["pct_irrecuperavel"] > 0
    out = tmp_path / "indice.csv"
    write_index(rows, out)
    back = read_index(out)
    assert len(back) == 2
    assert audit_index(back) == []


def test_build_reports_frontmatter_that_contradicts_the_text(tmp_path):
    folder = tmp_path / "corpus"
    folder.mkdir()
    shutil.copy(FIXTURES / "bad_class" / "revised.md", folder / "bad.md")
    rows, problems = build_rows(folder)
    assert rows and any("classe_calculada" in p for p in problems)


def test_build_skips_raw_files_without_frontmatter(tmp_path):
    folder = tmp_path / "corpus"
    folder.mkdir()
    shutil.copy(FIXTURES / "ok_minimal" / "raw.md", folder / "raw.md")
    rows, _ = build_rows(folder)
    assert rows == []


def test_index_cli(tmp_path, capsys):
    folder = tmp_path / "corpus"
    folder.mkdir()
    shutil.copy(FIXTURES / "ok_minimal" / "revised.md", folder / "a.md")
    assert main(["index", "build", str(folder), "--out", str(tmp_path / "i.csv")]) == 0
    assert (tmp_path / "i.csv").exists()
    assert main(["index", "audit", str(tmp_path / "i.csv")]) == 0
    with open(tmp_path / "old.csv", "w", encoding="utf-8", newline="") as f:
        rows = _old_style_rows()
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    assert main(["index", "audit", str(tmp_path / "old.csv")]) == 1
    assert "inconsistency" in capsys.readouterr().out


# -------------------------------------------------------------- summarize

def test_summary_lists_corrections_markers_and_review():
    log, issues = load_log(FIXTURES / "ok_markers" / "log.jsonl")
    text = render_summary(log)
    assert "agarmassa" in text and "argamassa" in text
    assert "tarbaldo vrzeni" in text and "`??`" in text
    assert "To review" in text and "c0005" in text
    assert "pontuacao: 30" in text


def test_summarize_cli_refuses_invalid_log(tmp_path, capsys):
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"type":"change"}\n', encoding="utf-8")
    assert main(["summarize", str(bad)]) == 1


def test_summarize_cli_writes_file(tmp_path):
    out = tmp_path / "s.md"
    assert main(["summarize", str(FIXTURES / "ok_minimal" / "log.jsonl"), "--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8").startswith("# Revision log")


# -------------------------------------------------------------------- cli

def test_check_cli_exit_codes_and_report(tmp_path):
    d = FIXTURES / "ok_minimal"
    args = [str(d / "raw.md"), str(d / "revised.md"), str(d / "log.jsonl"),
            "--lexicon", str(FIXTURES / "lexicon.json"), "--speakers", str(FIXTURES / "speakers.json")]
    assert main(["check", *args, "--report", str(tmp_path / "r.md")]) == 0
    assert "PASS" in (tmp_path / "r.md").read_text(encoding="utf-8")
    d = FIXTURES / "bad_fluent_swap"
    assert main(["check", str(d / "raw.md"), str(d / "revised.md"), str(d / "log.jsonl")]) == 1


def test_cli_missing_file_is_a_clean_error(capsys):
    assert main(["validate-log", "does-not-exist.jsonl"]) == 1
    assert "file not found" in capsys.readouterr().err


def test_classify_cli_write_fills_computed_fields(tmp_path, capsys):
    target = tmp_path / "x.md"
    text = (FIXTURES / "ok_markers" / "revised.md").read_text(encoding="utf-8")
    text = text.replace("classe_calculada: B", "classe_calculada: A").replace("pct_irrecuperavel: 1.45", "pct_irrecuperavel: 0.0")
    target.write_text(text, encoding="utf-8")
    assert main(["classify", str(target), "--write"]) == 0
    assert "classe_calculada: B" in target.read_text(encoding="utf-8")
    assert "detected='pt'" in capsys.readouterr().out


def test_hash_cli(capsys):
    assert main(["hash", str(FIXTURES / "ok_minimal" / "raw.md")]) == 0
    out = capsys.readouterr().out
    assert json.loads((FIXTURES / "ok_minimal" / "expected.json").read_text())  # fixture present
    assert len(out.split()[0]) == 64
