import contextlib
import errno
import fcntl
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import organize_movies as app


class OrganizerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="movie organizer test ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.movies = self.root / "movies one"
        self.movies.mkdir()
        self.incoming = self.movies / "Film (2026).mkv"
        self.destination = self.movies / "Film (2026)" / self.incoming.name

    def cli(self, *options, directories=None):
        return subprocess.run([str(ROOT / "organize_movies.sh"), *options,
                               *map(str, directories or [self.movies])],
                              cwd=self.root, capture_output=True, text=True, timeout=10)

    def run_app(self, *args, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            result = app.organize(*args, **kwargs)
        return result, output.getvalue()

    def conflict(self):
        self.incoming.write_bytes(b"new movie bytes")
        self.destination.parent.mkdir()
        self.destination.write_bytes(b"old movie bytes")

    def backups(self):
        base = self.movies / app.BACKUPS
        return sorted(p for p in base.rglob("*") if p.is_file()) if base.exists() else []

    def assert_originals(self):
        self.assertEqual(self.incoming.read_bytes(), b"new movie bytes")
        self.assertEqual(self.destination.read_bytes(), b"old movie bytes")

    def test_default_preview_makes_no_files_or_directories(self):
        self.incoming.write_bytes(b"movie")
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("WOULD MOVE", result.stdout)
        self.assertIn("planned=1, moved=0", result.stdout)
        self.assertEqual(list(self.movies.iterdir()), [self.incoming])

    def test_replace_preview_does_not_create_backup_or_move(self):
        self.conflict()
        result = self.cli("--on-existing", "replace")
        self.assertEqual(result.returncode, 0)
        self.assertIn("WOULD REPLACE", result.stdout)
        self.assert_originals()
        self.assertFalse((self.movies / app.BACKUPS).exists())

    def test_apply_moves_and_rerun_is_idempotent(self):
        self.incoming.write_bytes(b"unchanged movie content")
        os.chmod(self.incoming, 0o640)
        before = self.incoming.stat()
        result = self.cli("--apply")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(self.incoming.exists())
        self.assertEqual(self.destination.read_bytes(), b"unchanged movie content")
        after = self.destination.stat()
        self.assertEqual((after.st_dev, after.st_ino, after.st_mtime_ns, after.st_mode),
                         (before.st_dev, before.st_ino, before.st_mtime_ns, before.st_mode))
        result = self.cli("--apply")
        self.assertEqual(result.returncode, 0)
        self.assertIn("moved=0, replaced=0", result.stdout)

    def test_apply_skips_existing_by_default(self):
        self.conflict()
        result = self.cli("--apply")
        self.assertEqual(result.returncode, 0)
        self.assertIn("skipped=1", result.stdout)
        self.assert_originals()
        self.assertEqual(self.backups(), [])

    def test_replace_keeps_verified_old_bytes_and_new_file_metadata(self):
        self.conflict()
        old = b"old bytes" * 400000  # Exercise multiple backup-copy chunks.
        self.destination.write_bytes(old)
        os.chmod(self.destination, 0o640)
        old_stat = self.destination.stat()
        before = self.incoming.stat()
        result = self.cli("--apply", "--on-existing", "replace")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("replaced=1", result.stdout)
        self.assertFalse(self.incoming.exists())
        self.assertEqual(self.destination.read_bytes(), b"new movie bytes")
        self.assertEqual(self.destination.stat().st_ino, before.st_ino)
        backups = self.backups()
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), old)
        self.assertEqual(backups[0].stat().st_mtime_ns, old_stat.st_mtime_ns)
        self.assertEqual(backups[0].stat().st_mode & 0o777, 0o640)
        self.assertEqual(backups[0].parent.stat().st_mode & 0o777, 0o700)

    def test_repeated_replacements_never_overwrite_previous_backups(self):
        self.conflict()
        self.assertEqual(self.cli("--apply", "--on-existing", "replace").returncode, 0)
        self.incoming.write_bytes(b"third movie bytes")
        self.assertEqual(self.cli("--apply", "--on-existing", "replace").returncode, 0)
        self.assertEqual(len(self.backups()), 2)
        self.assertEqual({p.read_bytes() for p in self.backups()}, {b"old movie bytes", b"new movie bytes"})
        self.assertEqual(self.destination.read_bytes(), b"third movie bytes")

    def test_extensions_are_case_insensitive_and_old_formats_remain(self):
        for i, ext in enumerate(sorted(app.EXTENSIONS)):
            source = self.movies / (f"Movie {i}" + ext.upper())
            source.write_bytes(ext.encode())
        result = self.cli("--apply")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn(f"moved={len(app.EXTENSIONS)}", result.stdout)
        self.assertEqual(len(list(self.movies.rglob("*.*"))), len(app.EXTENSIONS))

    def test_special_names_remain_literal_and_log_on_one_line(self):
        names = ["-movie.mkv", "quotes ' and spaces.MP4", "semi; $(touch OWNED).avi",
                 "brackets [a]*?.mov", "newline\nmovie.mkv", "película 日本語.mkv"]
        for name in names:
            (self.movies / name).write_bytes(name.encode())
        result = self.cli("--apply")
        self.assertEqual(result.returncode, 0, result.stdout)
        for name in names:
            self.assertEqual((self.movies / Path(name).stem / name).read_bytes(), name.encode())
        self.assertFalse((self.root / "OWNED").exists())
        self.assertIn("newline\\nmovie", result.stdout)

    def test_sidecars_and_nested_movies_are_untouched(self):
        (self.movies / "Film.srt").write_bytes(b"subtitle")
        nested = self.movies / "Already Organized"
        nested.mkdir()
        (nested / "Other.mkv").write_bytes(b"nested movie")
        self.assertEqual(self.cli("--apply").returncode, 0)
        self.assertEqual((self.movies / "Film.srt").read_bytes(), b"subtitle")
        self.assertEqual((nested / "Other.mkv").read_bytes(), b"nested movie")

    def test_differently_named_release_is_not_guessed_as_replacement(self):
        self.conflict()
        different = self.destination.parent / "Different release.mp4"
        different.write_bytes(b"different release")
        self.assertEqual(self.cli("--apply", "--on-existing", "replace").returncode, 0)
        self.assertEqual(different.read_bytes(), b"different release")

    def test_symlink_source_is_rejected(self):
        outside = self.root / "outside.mkv"
        outside.write_bytes(b"outside")
        self.incoming.symlink_to(outside)
        result = self.cli("--apply")
        self.assertEqual(result.returncode, 1)
        self.assertTrue(self.incoming.is_symlink())
        self.assertEqual(outside.read_bytes(), b"outside")

    def test_symlink_folder_or_destination_is_rejected(self):
        self.incoming.write_bytes(b"new movie bytes")
        outside = self.root / "outside"
        outside.mkdir()
        self.destination.parent.symlink_to(outside, target_is_directory=True)
        self.assertEqual(self.cli("--apply", "--on-existing", "replace").returncode, 1)
        self.destination.parent.unlink()
        self.destination.parent.mkdir()
        self.destination.symlink_to(outside / "nonexistent.mkv")
        self.assertEqual(self.cli("--apply", "--on-existing", "replace").returncode, 1)
        self.assertTrue(self.incoming.exists())
        self.assertTrue(self.destination.is_symlink())
        self.assertEqual(list(outside.iterdir()), [])

    def test_destination_directory_or_folder_file_is_rejected(self):
        self.incoming.write_bytes(b"incoming")
        self.destination.parent.write_bytes(b"folder name is a file")
        self.assertEqual(self.cli("--apply").returncode, 1)
        self.destination.parent.unlink()
        self.destination.mkdir(parents=True)
        self.assertEqual(self.cli("--apply", "--on-existing", "replace").returncode, 1)
        self.assertEqual(self.incoming.read_bytes(), b"incoming")

    def test_same_inode_conflict_is_skipped_without_backup(self):
        self.incoming.write_bytes(b"hardlinked movie")
        self.destination.parent.mkdir()
        os.link(self.incoming, self.destination)
        result = self.cli("--apply", "--on-existing", "replace")
        self.assertEqual(result.returncode, 0)
        self.assertIn("SKIP same file", result.stdout)
        self.assertTrue(self.incoming.exists())
        self.assertEqual(self.backups(), [])

    def test_empty_movie_rejected(self):
        self.incoming.touch()
        self.assertEqual(self.cli("--apply").returncode, 1)
        self.assertTrue(self.incoming.exists())
        self.assertFalse(self.destination.parent.exists())

    def test_unsafe_and_reserved_stems_do_not_escape_directory(self):
        for name in ("..mkv", "...mp4", app.BACKUPS + ".mkv"):
            (self.movies / name).write_bytes(b"movie")
        self.assertEqual(self.cli("--apply").returncode, 1)
        self.assertEqual(len(list(self.movies.iterdir())), 3)
        self.assertFalse((self.root / "...mp4").exists())

    def test_multiple_directories_duplicate_alias_and_invalid_directory(self):
        second = self.root / "movies two"
        second.mkdir()
        (second / "Second.avi").write_bytes(b"second")
        self.incoming.write_bytes(b"first")
        result = self.cli("--apply", directories=[self.movies, second, self.movies / ".", self.root / "missing"])
        self.assertEqual(result.returncode, 1)
        self.assertIn("moved=2", result.stdout)
        self.assertIn("SKIP duplicate directory", result.stdout)
        self.assertTrue(self.destination.exists())
        self.assertTrue((second / "Second" / "Second.avi").exists())

    def test_directory_lock_prevents_changes_without_lockfile(self):
        self.incoming.write_bytes(b"movie")
        fd = os.open(self.movies, os.O_RDONLY | os.O_DIRECTORY)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(self.cli("--apply").returncode, 1)
        finally:
            os.close(fd)
        self.assertEqual(list(self.movies.iterdir()), [self.incoming])

    def test_backup_failure_prevents_replacement(self):
        self.conflict()
        with patch.object(app, "digest_file", side_effect=OSError(errno.ENOSPC, "simulated disk full")):
            counts, output = self.run_app([self.movies], apply=True, on_existing="replace")
        self.assertEqual(counts.errors, 1)
        self.assertEqual(counts.replaced, 0)
        self.assertNotIn("REPLACED:", output)
        self.assert_originals()
        self.assertEqual(self.backups(), [])

    def test_backup_hash_mismatch_prevents_replacement(self):
        self.conflict()
        with patch.object(app, "digest_file", return_value=b"wrong digest"):
            counts, _ = self.run_app([self.movies], apply=True, on_existing="replace")
        self.assertEqual(counts.errors, 1)
        self.assert_originals()

    def test_failed_replacement_keeps_both_files_and_backup(self):
        self.conflict()
        with patch.object(app.os, "replace", side_effect=OSError(errno.EXDEV, "cross-device rename")):
            counts, _ = self.run_app([self.movies], apply=True, on_existing="replace")
        self.assertEqual(counts.errors, 1)
        self.assertEqual(counts.replaced, 0)
        self.assert_originals()
        self.assertEqual(self.backups()[0].read_bytes(), b"old movie bytes")

    def test_backup_root_symlink_rejected(self):
        self.conflict()
        outside = self.root / "outside"
        outside.mkdir()
        (self.movies / app.BACKUPS).symlink_to(outside, target_is_directory=True)
        self.assertEqual(self.cli("--apply", "--on-existing", "replace").returncode, 1)
        self.assert_originals()
        self.assertEqual(list(outside.iterdir()), [])

    def test_destination_created_after_scan_is_never_overwritten(self):
        self.incoming.write_bytes(b"incoming")
        original = os.link

        def race(source, destination, **kwargs):
            destination.write_bytes(b"concurrent destination")
            return original(source, destination, **kwargs)

        with patch.object(app.os, "link", side_effect=race):
            counts, _ = self.run_app([self.movies], apply=True)
        self.assertEqual(counts.errors, 1)
        self.assertEqual(self.incoming.read_bytes(), b"incoming")
        self.assertEqual(self.destination.read_bytes(), b"concurrent destination")

    def test_failed_source_unlink_rolls_back_new_link(self):
        self.incoming.write_bytes(b"incoming")
        original = Path.unlink

        def fail_source(path, *args, **kwargs):
            if path == self.incoming:
                raise PermissionError("simulated unlink failure")
            return original(path, *args, **kwargs)

        with patch.object(Path, "unlink", fail_source):
            counts, _ = self.run_app([self.movies], apply=True)
        self.assertEqual(counts.errors, 1)
        self.assertEqual(counts.moved, 0)
        self.assertEqual(self.incoming.read_bytes(), b"incoming")
        self.assertFalse(self.destination.exists())
        self.assertFalse(self.destination.parent.exists())

    def test_unsupported_hardlinks_fail_without_deleting_source(self):
        self.incoming.write_bytes(b"incoming")
        with patch.object(app.os, "link", side_effect=OSError(errno.EOPNOTSUPP, "hard links unsupported")):
            counts, _ = self.run_app([self.movies], apply=True)
        self.assertEqual(counts.errors, 1)
        self.assertTrue(self.incoming.exists())
        self.assertFalse(self.destination.parent.exists())

    def test_change_during_backup_cancels_replacement(self):
        self.conflict()
        original = app.backup_existing

        def changed(destination, root, before):
            backup = original(destination, root, before)
            self.incoming.write_bytes(b"changed incoming")
            return backup

        with patch.object(app, "backup_existing", side_effect=changed):
            counts, _ = self.run_app([self.movies], apply=True, on_existing="replace")
        self.assertEqual(counts.errors, 1)
        self.assertEqual(self.incoming.read_bytes(), b"changed incoming")
        self.assertEqual(self.destination.read_bytes(), b"old movie bytes")

    def test_destination_change_after_backup_cancels_replacement(self):
        self.conflict()
        original = app.backup_existing

        def changed(destination, root, before):
            backup = original(destination, root, before)
            destination.write_bytes(b"another writer's movie")
            return backup

        with patch.object(app, "backup_existing", side_effect=changed):
            counts, _ = self.run_app([self.movies], apply=True, on_existing="replace")
        self.assertEqual(counts.errors, 1)
        self.assertEqual(self.incoming.read_bytes(), b"new movie bytes")
        self.assertEqual(self.destination.read_bytes(), b"another writer's movie")
        self.assertEqual(self.backups()[0].read_bytes(), b"old movie bytes")

    def test_interruption_during_backup_does_not_replace(self):
        self.conflict()
        with patch.object(app, "digest_file", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.run_app([self.movies], apply=True, on_existing="replace")
        self.assert_originals()
        self.assertEqual(self.backups(), [])

    def test_empty_directory_is_a_successful_noop(self):
        result = self.cli("--apply")
        self.assertEqual(result.returncode, 0)
        self.assertIn("planned=0, moved=0, replaced=0, skipped=0, errors=0", result.stdout)
        self.assertEqual(list(self.movies.iterdir()), [])

    def test_existing_hardlink_elsewhere_keeps_original_bytes_after_replacement(self):
        self.conflict()
        torrent = self.root / "seeding copy.mkv"
        os.link(self.destination, torrent)
        self.assertEqual(self.cli("--apply", "--on-existing", "replace").returncode, 0)
        self.assertEqual(torrent.read_bytes(), b"old movie bytes")
        self.assertEqual(self.destination.read_bytes(), b"new movie bytes")

    def test_no_arguments_and_conflicting_modes_fail_without_changes(self):
        result = subprocess.run([str(ROOT / "organize_movies.sh")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.cli("--apply", "--dry-run").returncode, 2)
        self.assertEqual(list(self.movies.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
