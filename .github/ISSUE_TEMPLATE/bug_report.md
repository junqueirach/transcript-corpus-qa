---
name: Bug report
about: The checker accepted something it should have rejected, or the reverse
title: ""
labels: bug
assignees: ""
---

**What happened**
A clear description. If the checker passed a revision that changed the text silently, that is the most important kind of bug: please say so.

**Minimal example**
Three small files (raw, revised, log) with *invented* text that reproduce it. Do not paste real transcripts.

**Command and output**
```
tcqa check raw.md revised.md log.jsonl
```

**Environment**
- OS:
- Python version:
- tcqa version (`tcqa --version`):
