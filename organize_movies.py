#!/usr/bin/env python3
"""Preview or organize loose movie files, with optional backed-up replacement."""

import argparse
import contextlib
from dataclasses import dataclass
import datetime
import fcntl
import hashlib
import os
from pathlib import Path
import signal
import stat
import sys
import tempfile


EXTENSIONS = {".mp4", ".mkv", ".avi", ".m4v", ".wmv", ".ogv", ".mov", ".divx", ".mpg", ".mpeg", ".m2ts", ".webm"}
BACKUPS = ".movie-organizer-backups"


class OrganizeError(Exception):
    pass


@dataclass
class Counts:
    planned: int = 0
    moved: int = 0
    replaced: int = 0
    skipped: int = 0
    errors: int = 0


def info(message):
    print(message, flush=True)


def snapshot(path):
    try:
        return path.lstat()
    except FileNotFoundError:
        return None


def identity(details):
    return (details.st_dev, details.st_ino, details.st_size, details.st_mtime_ns, details.st_ctime_ns)


def unchanged(path, before):
    after = snapshot(path)
    if after is None or identity(after) != identity(before):
        raise OrganizeError(f"File changed during the operation: {str(path)!r}; retry after stopping other writers.")


def sync_directory(directory):
    with contextlib.ExitStack() as stack:
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        stack.callback(os.close, fd)
        os.fsync(fd)


def safe_directory(path):
    details = snapshot(path)
    if details is not None and not stat.S_ISDIR(details.st_mode):
        raise OrganizeError(f"Expected a real directory, not a file or symlink: {str(path)!r}")
    return details


def digest_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.digest()


def backup_existing(destination, root, before):
    """Copy and verify old bytes before allowing replacement; never reuse a backup name."""
    base = root / BACKUPS
    safe_directory(base)
    base.mkdir(mode=0o700, exist_ok=True)
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ-")
    directory = Path(tempfile.mkdtemp(prefix=timestamp, dir=base))
    backup = directory / destination.name
    try:
        unchanged(destination, before)
        flags = os.O_RDONLY | os.O_NOFOLLOW
        with os.fdopen(os.open(destination, flags), "rb") as incoming, backup.open("xb") as out:
            if identity(os.fstat(incoming.fileno())) != identity(before):
                raise OrganizeError("Destination changed before backup; replacement cancelled.")
            expected = hashlib.sha256()
            for chunk in iter(lambda: incoming.read(1024 * 1024), b""):
                expected.update(chunk)
                out.write(chunk)
            # Preserve basic mode and timestamps; ownership/ACLs are not copied.
            os.fchmod(out.fileno(), stat.S_IMODE(before.st_mode) & 0o777)
            out.flush()
            os.fsync(out.fileno())
        os.utime(backup, ns=(before.st_atime_ns, before.st_mtime_ns))
        if digest_file(backup) != expected.digest():
            raise OrganizeError("Backup verification failed; replacement cancelled.")
        unchanged(destination, before)
        sync_directory(directory)
        sync_directory(base)
        sync_directory(root)
        return backup
    except BaseException:
        # A failed backup must never authorize a replacement.
        with contextlib.suppress(OSError):
            backup.unlink(missing_ok=True)
            directory.rmdir()
        raise


def move_without_overwrite(source, destination, before):
    """An exclusive hard-link creation protects even a destination created after the scan."""
    unchanged(source, before)
    os.link(source, destination, follow_symlinks=False)
    try:
        # Source ctime changes when a hard link is added; verify inode, bytes, and mtime.
        current = source.lstat()
        linked = destination.lstat()
        original = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        if any((s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns) != original for s in (current, linked)):
            raise OrganizeError("Source changed while moving; source was retained.")
        # Persist the new directory entry before removing the source name.
        sync_directory(destination.parent)
        source.unlink()
    except BaseException:
        # Roll back our link if the source still exists and refers to the same file.
        with contextlib.suppress(OSError):
            if source.exists() and os.path.samestat(source.lstat(), destination.lstat()):
                destination.unlink()
        raise


def organize_one(source, root, apply, on_existing, counts):
    before = source.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise OrganizeError(f"Skipping nonregular movie file (including symlink): {str(source)!r}")
    if before.st_size == 0:
        raise OrganizeError(f"Skipping empty movie file: {str(source)!r}")
    stem = source.stem
    if stem in ("", ".", "..", BACKUPS):
        raise OrganizeError(f"Unsafe or reserved folder name for {source.name!r}")
    folder = root / stem
    folder_before = safe_directory(folder)
    destination = folder / source.name
    old = snapshot(destination)
    if old is not None:
        if not stat.S_ISREG(old.st_mode):
            raise OrganizeError(f"Destination is not a regular file: {str(destination)!r}")
        if os.path.samestat(before, old):
            counts.skipped += 1
            info(f"SKIP same file: {str(source)!r}")
            return
        if on_existing == "skip":
            counts.skipped += 1
            info(f"SKIP existing destination: {str(destination)!r}")
            return
    action = "REPLACE" if old is not None else "MOVE"
    if not apply:
        counts.planned += 1
        info(f"WOULD {action}: {str(source)!r} -> {str(destination)!r}" +
             (" (back up existing file first)" if old is not None else ""))
        return
    created = False
    try:
        if folder_before is None:
            folder.mkdir()  # If another process created it, fail and rescan on a later run.
            created = True
        else:
            current = safe_directory(folder)
            if current is None or (current.st_dev, current.st_ino) != (folder_before.st_dev, folder_before.st_ino):
                raise OrganizeError("Destination folder changed; operation cancelled.")
        unchanged(source, before)
        if old is not None:
            backup = backup_existing(destination, root, old)
            info(f"BACKUP: {str(backup)!r}")
            unchanged(source, before)
            unchanged(destination, old)
            # Rename replaces one directory entry atomically, without modifying other hard links.
            os.replace(source, destination)
            counts.replaced += 1
            sync_directory(folder)
            sync_directory(root)
        else:
            move_without_overwrite(source, destination, before)
            counts.moved += 1
            sync_directory(root)
        info(f"{action}D: {str(source)!r} -> {str(destination)!r}" if action == "REPLACE"
             else f"MOVED: {str(source)!r} -> {str(destination)!r}")
    finally:
        if created:
            with contextlib.suppress(OSError):
                folder.rmdir()  # Only remove an empty directory created by this operation.


def organize(directories, apply=False, on_existing="skip"):
    counts = Counts()
    seen = set()
    for value in directories:
        try:
            root = Path(value).resolve(strict=True)
            if root == Path(root.anchor):
                raise OrganizeError("A filesystem root is not a movie directory.")
            with contextlib.ExitStack() as stack:
                fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                stack.callback(os.close, fd)
                details = os.fstat(fd)
                key = (details.st_dev, details.st_ino)
                if key in seen:
                    info(f"SKIP duplicate directory: {str(root)!r}")
                    continue
                seen.add(key)
                try:
                    # Lock the directory itself: preview creates no lock files or directories.
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise OrganizeError(f"Another organizer is using {str(root)!r}") from None
                info(f"{'APPLY' if apply else 'PREVIEW'}: {str(root)!r}")
                sources = sorted(p for p in root.iterdir() if p.suffix.lower() in EXTENSIONS)
                for source in sources:
                    try:
                        # Existing movie folders are outside this top-level-file scan.
                        if stat.S_ISDIR(source.lstat().st_mode):
                            continue
                        organize_one(source, root, apply, on_existing, counts)
                    except (OSError, OrganizeError) as error:
                        counts.errors += 1
                        info(f"ERROR {str(source)!r}: {error}")
        except (OSError, OrganizeError, RuntimeError) as error:
            counts.errors += 1
            info(f"ERROR directory {str(value)!r}: {error}")
    info(f"Summary: planned={counts.planned}, moved={counts.moved}, replaced={counts.replaced}, "
         f"skipped={counts.skipped}, errors={counts.errors}")
    if not apply:
        info("Preview only. Add --apply to change files; use --on-existing replace for backed-up replacement.")
    return counts


def interrupted(_signum, _frame):
    raise KeyboardInterrupt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="Actually move files (default: preview)")
    mode.add_argument("--dry-run", action="store_true", help="Preview only; make no changes (the default)")
    parser.add_argument("--on-existing", choices=("skip", "replace"), default="skip",
                        help="Exact destination filename conflict: skip, or back up then replace")
    parser.add_argument("directories", nargs="+", help="Directories containing loose movie files; no recursive scan")
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, interrupted)
    try:
        return int(organize(args.directories, args.apply, args.on_existing).errors > 0)
    except KeyboardInterrupt:
        info("Interrupted. Check the reported paths before resuming; completed moves/backups are retained.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
