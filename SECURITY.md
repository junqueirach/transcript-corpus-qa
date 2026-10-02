# Security policy

`tcqa` is an offline command-line tool. It reads the files you pass on the
command line, writes the report or index you ask for, and makes no network
connections. It does not execute content from the files it reads.

## Reporting a problem

If you find a way to make the checker **accept a revision that silently changed
the text** (a false pass), please treat it as a security issue for people who
rely on the tool for corpus integrity: open a private security advisory on this
repository or contact the maintainer through the GitHub profile rather than
filing a public issue with the details. Ordinary bugs go to the issue tracker.

## Scope notes

- Front matter is parsed with a small, deliberate YAML subset; no YAML library
  and no code execution.
- Logs are JSON Lines parsed with the standard library.
- The lexicon and speaker registry are plain JSON.
- Supported Python versions: 3.10 and later. No third-party runtime
  dependencies.
