"""Render a check result as Markdown (for files) or plain text (terminal)."""
from __future__ import annotations

from .checker import Result

CHECK_NAMES = {
    "C0": "log validity", "C1": "unlogged difference", "C2": "log entry without a difference",
    "C3": "marker content altered", "C4": "silent deletion", "C5": "net length",
    "C6": "added words", "C7": "front matter and counts", "C8": "quality class",
    "C9": "readiness flags", "C10": "speaker labels", "C11": "tiers and confidence",
    "C12": "raw hash", "C13": "translation parity", "C14": "proper-name guard",
}


def _cell(text: str, limit: int = 70) -> str:
    text = " ".join(str(text).split())
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return text.replace("|", "\\|")


def summary_line(result: Result) -> str:
    status = "PASS" if result.passed else "FAIL"
    return f"{status} — {len(result.errors)} error(s), {len(result.warnings)} warning(s)"


def render_markdown(result: Result, raw_name: str, revised_name: str, log_name: str) -> str:
    lines = [f"# tcqa check report", "",
             f"**{summary_line(result)}**", "",
             f"- raw: `{raw_name}`", f"- revised: `{revised_name}`", f"- log: `{log_name}`", ""]
    st = result.stats
    if st:
        lines += ["## Numbers", "", "| what | value |", "|---|---|"]
        for key in ("raw_words", "revised_words", "hunks", "hesitation_hunks", "hesitation_words_removed",
                    "explained_hunks", "unexplained_hunks", "marker_violations", "markers_?", "markers_??",
                    "accent_or_case_only", "log_entries", "language_detected", "raw_sha256"):
            if key in st:
                lines.append(f"| {key} | {st[key]} |")
        lines.append("")
    if result.computed:
        c = result.computed
        lines += ["## Computed quality", "",
                  f"- body words: {c.palavras_corpo}; words inside `[[?? ]]`: {c.palavras_irrecuperaveis} ({c.pct_irrecuperavel} %)",
                  f"- markers: {c.trechos_incertos} × `[[? ]]`, {c.trechos_irrecuperaveis} × `[[?? ]]`",
                  f"- computed class: **{c.classe_calculada}**" + (f" (degraded section {c.secao_degradada})" if c.secao_degradada else ""),
                  f"- apto_rag: {c.apto_rag}; apto_finetuning: {c.apto_finetuning}", ""]
    findings = [f for f in result.findings if f.severity in ("error", "warning")]
    lines += ["## Findings", ""]
    if not findings:
        lines.append("None. Every difference between raw and revised is mechanical, a listed filler, a marker wrapping the original, or explained by the log.")
    else:
        lines += ["| severity | check | ¶ | raw | revised | explanation |", "|---|---|---|---|---|---|"]
        for f in sorted(findings, key=lambda f: (f.severity != "error", f.check, f.para or 0)):
            lines.append(f"| {f.severity} | {f.check} {CHECK_NAMES.get(f.check, '')} | {f.para or ''} | {_cell(f.raw)} | {_cell(f.revised)} | {_cell(f.message, 160)} |")
    accepted = [f for f in result.findings if f.severity == "info" and "— accepted:" in f.message]
    if accepted:
        lines += ["", "### Accepted warnings (examined by the reviser, reason in the log)", ""]
        lines += [f"- {f.check}{' ¶' + str(f.para) if f.para else ''}: {_cell(f.message, 240)}" for f in accepted]
    lines.append("")
    lines += ["## Review list (risky corrections and suggestions)", ""]
    if not result.review:
        lines.append("Nothing to review: no T3/T4 corrections, no medium/low suggestions, no new speakers.")
    else:
        lines += ["| id | ¶ | tier | conf. | raw | revised | basis |", "|---|---|---|---|---|---|---|"]
        for r in result.review:
            if r.get("kind") == "falante_novo":
                lines.append(f"| new speaker | {r.get('para') or ''} | | | | {_cell(r['nome'])} | quote: {_cell(r['citacao'])} |")
            else:
                lines.append(f"| {r.get('id')} | {r.get('para') or ''} | {r.get('tier') or ''} | {r.get('confidence') or ''} | {_cell(r.get('raw'))} | {_cell(r.get('revised'))} | {_cell(r.get('basis'), 120)} |")
    lines.append("")
    return "\n".join(lines)


def render_text(result: Result) -> str:
    out = [summary_line(result)]
    for f in sorted(result.findings, key=lambda f: (f.severity != "error", f.check, f.para or 0)):
        if f.severity not in ("error", "warning"):
            continue
        where = f" ¶{f.para}" if f.para else ""
        spans = ""
        if f.raw or f.revised:
            spans = f"  [{_cell(f.raw, 40)}] -> [{_cell(f.revised, 40)}]"
        out.append(f"  {f.severity.upper():7} {f.check:<4}{where}: {f.message}{spans}")
    st = result.stats
    if st:
        out.append(f"  words raw/revised: {st.get('raw_words')}/{st.get('revised_words')}; hunks: {st.get('hunks')} "
                   f"(fillers {st.get('hesitation_hunks')}, explained {st.get('explained_hunks')}, unexplained {st.get('unexplained_hunks')})")
    n_acc = sum(1 for f in result.findings if f.severity == "info" and "— accepted:" in f.message)
    if n_acc:
        out.append(f"  accepted warnings: {n_acc} (reasons in the log and the report)")
    if result.review:
        out.append(f"  review list: {len(result.review)} item(s) — see the Markdown report")
    return "\n".join(out)
