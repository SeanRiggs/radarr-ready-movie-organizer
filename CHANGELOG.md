# Changelog

## 2.0.0 — 2026-10-27

- Make preview the default and require `--apply` to move files.
- Add explicit `--on-existing replace` with unique, verified backups before replacement.
- Preserve skip-existing behavior as the default when applying.
- Keep the shell entry point and use a shared Python 3.10+ implementation with directory arguments.
- Handle extension case and unusual filenames consistently; avoid shell expansion and `ls` parsing.
- Add no-overwrite moves, directory locking, symlink/change checks, and accurate summaries/exit statuses.
- Add regression tests and CI across three Python versions.
- Replace duplicated README code with usage, replacement, recovery, and migration guidance.
