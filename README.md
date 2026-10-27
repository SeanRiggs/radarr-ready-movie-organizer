# Radarr-Ready Movie Organizer

Put loose movie files into folders—and deliberately replace an existing file when that is what you intend.

**Preview is the default.** Adding `--apply` moves files. Existing destination files are skipped unless you also select `--on-existing replace`; that mode copies and verifies a backup before replacing anything.

[![Tests](https://github.com/SeanRiggs/radarr-ready-movie-organizer/actions/workflows/test.yml/badge.svg)](https://github.com/SeanRiggs/radarr-ready-movie-organizer/actions/workflows/test.yml)

## What it does

For each supported loose movie file directly inside a directory you supply:

```text
/movies/Film (2026).mkv
          ↓
/movies/Film (2026)/Film (2026).mkv
```

The filename without its last extension becomes the folder name. Original filenames and file contents are preserved. Existing subdirectories are not scanned, and sidecars such as subtitles, artwork, and NFO files are left in place.

This is a **local file organizer**, not a Radarr API integration or a movie-identification service. It does not decide which release has better quality, rename releases from metadata, update Radarr's database, or guarantee that a folder will match a movie. Use Radarr's own import/upgrade workflow when you need movie identification and quality decisions; see the [Radarr library documentation](https://wiki.servarr.com/radarr/library).

## Install

Use **Linux with Python 3.10+**. There are no pip dependencies, Docker images, or API tokens to configure.

```sh
git clone https://github.com/SeanRiggs/radarr-ready-movie-organizer.git
cd radarr-ready-movie-organizer
./organize_movies.sh --help
```

The shell entry point calls `organize_movies.py` beside it. Keep both files together. It works from any working directory; directory arguments may be absolute or relative to where you run the command.

## Choose the behavior

### Preview without changing files

```sh
./organize_movies.sh /data/media/movies /data/media2/movies2
```

No movie folders, backups, or lock files are created. `--dry-run` is an explicit alias for this default behavior.

### Organize while skipping existing files

```sh
./organize_movies.sh --apply /data/media/movies
```

If `/data/media/movies/Film (2026)/Film (2026).mkv` already exists, the incoming loose `Film (2026).mkv` stays where it is. The destination is untouched.

### Preview replacements, then apply them

```sh
./organize_movies.sh --on-existing replace /data/media/movies
./organize_movies.sh --apply --on-existing replace /data/media/movies
```

For an **exact destination filename conflict**, replacement mode:

1. Copies the existing destination file into a unique backup directory.
2. Verifies the copied bytes with SHA-256 and checks that neither source nor destination changed during preparation.
3. Atomically renames the incoming file over that destination. The old file remains in its backup.

Example backup path:

```text
/data/media/movies/.movie-organizer-backups/20261027T120000Z-unique/Film (2026).mkv
```

Each replacement gets a new private backup directory. Repeated runs never reuse or overwrite an earlier backup. The output prints the exact backup path. The backup requires enough free space for the **entire previous file**, and copying/verifying a large movie takes time.

**Replacement is based on the exact path, not the movie title.** `Film.1080p.mkv` and `Film.2160p.mkv` become different folders; this tool will not infer that one upgrades the other. If a destination folder contains another filename or extension, that file is left alone.

## File handling and reporting

- Supported extensions, case-insensitively: `.mp4`, `.mkv`, `.avi`, `.m4v`, `.wmv`, `.ogv`, `.mov`, `.divx`, `.mpg`, `.mpeg`, `.m2ts`, `.webm`.
- Spaces, quotes, Unicode, leading dashes, glob characters, and newlines in filenames are handled literally. Printed paths are escaped so control characters do not become extra log lines.
- Empty movie files, symlink movie files, symlink destination folders/files, and unsafe folder names are rejected.
- A source already hard-linked to the exact destination is skipped, even in replacement mode.
- An exclusive directory lock prevents two copies of this organizer from processing the same directory at once. Duplicate directory arguments are processed once.
- Each run prints individual actions and totals for planned, moved, replaced, skipped, and failed operations. A failure does not produce a blanket success message.

Exit status: `0` for a completed preview/apply run, including intentional skips; `1` if any directory or file operation failed; `2` for invalid command arguments; `130` for interruption. Other valid files/directories may still be processed after an individual error. The summary counts completed moves/replacements even if a later durability flush fails; inspect any reported errors before rerunning.

At least one directory is required. For a directory name beginning with a dash, use an absolute path or put `--` before directory arguments.

## Before applying to a library

Pause other programs that may import, rename, or write these files, including Radarr imports and download post-processing. The lock coordinates this tool's instances; it does not lock out Radarr, a downloader, or someone editing files manually. Change checks catch many concurrent modifications but do not eliminate the final race with unrelated writers.

Run as the account that owns the library files and directories. Start with preview and a small test directory. Do not use this to reorganize an actively managed Radarr library without a plan to reconcile its paths afterward. Media-server database updates are outside this tool's scope.

Normal moves use exclusive hard-link creation followed by removal of the loose source name. This prevents accidentally overwriting a destination that appeared after scanning, preserves the file's inode/metadata, and requires both paths to be on the same filesystem with hard-link support. Replacement uses a same-filesystem rename after backup. Filesystems without hard links or directory `fsync` support, and destination folders mounted on another filesystem, may fail; there is no silent copy-and-delete fallback.

Backups retain old bytes, basic permissions, and timestamps, but do not preserve original ownership, ACLs, or every filesystem attribute. Replacement preserves the incoming file's inode and metadata; other hard links to the old movie retain the old bytes. File extensions and nonzero size do not prove that a video is playable or is an upgrade.

Completed operations and backups are retained if a later operation fails. This is not a transaction across a whole library. A forced kill or power loss during a normal link/unlink move can leave both names referring to the same file; a rerun skips that case for manual review. Interrupted backup creation can leave a partial backup directory—only a successfully verified backup permits replacement. Keep regular independent library backups as well.

## Restore a replacement

The `BACKUP:` line identifies the previous file. Stop programs that write to the library, preserve the current destination elsewhere if you want to keep it, then restore the backed-up file to its original destination. The original destination is the supplied movie directory followed by the backup filename without its extension, then the complete backup filename. Check contents and permissions before resuming imports.

Backups are not automatically pruned. Review them and remove only those you no longer need. Avoid exposing the hidden backup directory through a public file server; keep it outside any recursive media scan, or exclude it in that scanner's settings.

## Upgrading from the original script

Version 2 removes the embedded `MOVIE_DIRS` array and immediate execution behavior. Supply directory paths as command arguments and add `--apply` only after reviewing a preview. Existing cron jobs calling the old script with no arguments now exit with usage status `2`; update or disable them before installing this version.

The original `organize_movies.sh` filename remains, but it now requires its companion Python file and Python 3.10+. Do not replace only the shell file. The old README's duplicated script has been removed so the runnable source is authoritative.

## Tests and contributions

```sh
sh -n organize_movies.sh
python3 -m unittest discover -s tests -v
```

Tests create disposable libraries and exercise the actual command-line entry point. They cover preview, organization, replacement/backups, repeated replacements, literal filenames, symlink rejection, locking, failure reporting, concurrent destination creation, change detection, backup verification, and injected filesystem failures. No real media library or Radarr instance is required. GitHub Actions runs the suite on Python 3.10, 3.12, and 3.14.

Contributions are welcome. Add a regression test for changed file behavior, keep preview free of filesystem changes, and use synthetic movie files in test fixtures and bug reports. Do not include private library paths or credentials in public reports.

MIT licensed; see [LICENSE](LICENSE).
