"""Command-line interface: ``tcqa check | classify | validate-log | index | backup | summarize``."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .checker import run_check, sha256_bytes
from .classify import compute
from .frontmatter import join_document, split_document
from .language import detect_language
from .log import has_errors, load_log
from .report import render_markdown, render_text
from .resources import load_lexicon, load_speakers
from .textnorm import analyze


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def cmd_check(args: argparse.Namespace) -> int:
    raw_path, rev_path, log_path = Path(args.raw), Path(args.revised), Path(args.log)
    raw_bytes = raw_path.read_bytes()
    log, issues = load_log(log_path)
    result = run_check(
        raw_bytes.decode("utf-8"), _read(rev_path), log, issues,
        lexicon=load_lexicon(args.lexicon), speakers=load_speakers(args.speakers),
        raw_bytes=raw_bytes, max_deletion=args.max_deletion,
        finetune_languages=set(args.finetune_languages.split(",")) if args.finetune_languages else None,
    )
    print(render_text(result))
    if args.report:
        Path(args.report).write_text(render_markdown(result, raw_path.name, rev_path.name, log_path.name), encoding="utf-8")
        print(f"  report written to {args.report}")
    return result.exit_code(strict=args.strict)


def cmd_classify(args: argparse.Namespace) -> int:
    path = Path(args.revised)
    text = _read(path)
    doc = analyze(text)
    fm = doc.frontmatter if doc.header_kind == "yaml" else {}
    detected, conf = detect_language(doc.body)
    declared = fm.get("idioma")
    derived = fm.get("derivado_de") is not None
    comp = compute(doc, derived=derived, language=declared or detected,
                   finetune_languages=set(args.finetune_languages.split(",")) if args.finetune_languages else None)
    print(f"file: {path.name}")
    print(f"language: declared={declared!r} detected={detected!r} (confidence {conf})")
    for key, value in comp.as_frontmatter().items():
        print(f"{key}: {value}")
    print(f"palavras_irrecuperaveis: {comp.palavras_irrecuperaveis}")
    if declared and detected and declared.split('-')[0].casefold() != detected:
        print("WARNING: declared language and detected language differ", file=sys.stderr)
    if args.write:
        if doc.header_kind != "yaml":
            print("cannot --write: the file has no YAML front matter", file=sys.stderr)
            return 1
        fm = dict(fm)
        fm.update(comp.as_frontmatter())
        if fm.get("idioma") is None and detected:
            fm["idioma"] = detected
        if fm.get("classe_qualidade") in (None, ""):
            fm["classe_qualidade"] = comp.classe_calculada
        _, body, _ = split_document(text)
        path.write_text(join_document(fm, body), encoding="utf-8")
        print(f"front matter updated in {path}")
    return 0


def cmd_validate_log(args: argparse.Namespace) -> int:
    log, issues = load_log(Path(args.log))
    for issue in issues:
        print(issue)
    n = len(log.changes) if log else 0
    print(f"{'INVALID' if has_errors(issues) else 'VALID'} — {n} change entries, {len(issues)} issue(s)")
    return 1 if has_errors(issues) else 0


def cmd_hash(args: argparse.Namespace) -> int:
    for name in args.files:
        print(f"{sha256_bytes(Path(name).read_bytes())}  {name}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tcqa", description="Fidelity checker for revised speech-to-text transcripts.")
    p.add_argument("--version", action="version", version=f"tcqa {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    c = sub.add_parser("check", help="compare raw, revised and log; exit 0 pass, 1 fail, 2 warnings only")
    c.add_argument("raw", help="raw ASR file (or, for a translation, its source revised file)")
    c.add_argument("revised"); c.add_argument("log")
    c.add_argument("--lexicon"); c.add_argument("--speakers")
    c.add_argument("--report", help="write a Markdown report to this path")
    c.add_argument("--strict", action="store_true", help="warnings also fail (exit 1)")
    c.add_argument("--max-deletion", type=int, default=8, help="consecutive unlogged deleted words that count as a silent deletion (C4)")
    c.add_argument("--finetune-languages", help="comma-separated languages allowed for fine-tuning (decision D5); default: all")
    c.set_defaults(func=cmd_check)

    k = sub.add_parser("classify", help="compute class, counts and flags of a revised file")
    k.add_argument("revised"); k.add_argument("--write", action="store_true", help="update the computed fields in the front matter")
    k.add_argument("--finetune-languages")
    k.set_defaults(func=cmd_classify)

    v = sub.add_parser("validate-log", help="validate a JSONL log against the schema rules")
    v.add_argument("log"); v.set_defaults(func=cmd_validate_log)

    h = sub.add_parser("hash", help="print the SHA-256 of files (for raw_sha256)")
    h.add_argument("files", nargs="+"); h.set_defaults(func=cmd_hash)

    from .index import add_index_parser  # noqa: E402  (keeps cli importable even if index grows)
    from .backup import add_backup_parser  # noqa: E402
    from .summarize import add_summarize_parser  # noqa: E402
    add_index_parser(sub)
    add_backup_parser(sub)
    add_summarize_parser(sub)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except FileNotFoundError as exc:
        print(f"tcqa: file not found: {exc.filename}", file=sys.stderr)
        return 1
    except UnicodeDecodeError as exc:
        print(f"tcqa: not valid UTF-8 ({exc.reason}); all files must be UTF-8", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
