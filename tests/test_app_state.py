from __future__ import annotations

import json
import os
import sys
import tempfile
import multiprocessing
import time
import unittest
from pathlib import Path
from unittest import mock


APP_DIR = Path(__file__).resolve().parents[1] / "app"
os.environ.setdefault("RESTREAM_CONTROL_DATA_DIR", tempfile.mkdtemp(prefix="restream-control-tests-"))
sys.path.insert(0, str(APP_DIR))

import app_state  # noqa: E402


def increment_saved_state(path, key):
    for _ in range(20):
        def update(data):
            data[key] = data.get(key, 0) + 1
            data["total"] = data.get("total", 0) + 1
            return data
        app_state.update_json(Path(path), update)


def interrupt_before_replace(path, ready):
    def blocked_replace(source, destination):
        ready.set()
        time.sleep(30)
    with mock.patch.object(app_state.os, "replace", side_effect=blocked_replace):
        app_state.save_json(Path(path), {"value": "new"})


class AtomicStateTests(unittest.TestCase):
    def test_transient_windows_sharing_conflict_is_retried(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.json"
            with mock.patch.object(Path, "read_text", side_effect=[PermissionError("sharing"), '{"saved": true}']):
                self.assertEqual(app_state.load_json(path, {}), {"saved": True})
            original_replace = os.replace
            calls = []
            def replace(source, destination):
                calls.append(source)
                if len(calls) == 1:
                    raise PermissionError("sharing")
                original_replace(source, destination)
            with mock.patch.object(app_state.os, "replace", side_effect=replace):
                app_state.save_json(path, {"saved": True})
            self.assertEqual(len(calls), 2)
            self.assertEqual(app_state.load_json(path, {}), {"saved": True})

    def test_failed_replace_preserves_previous_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.json"
            app_state.save_json(path, {"saved": True})
            with mock.patch.object(app_state.os, "replace", side_effect=OSError("simulated interruption")):
                with self.assertRaises(OSError):
                    app_state.save_json(path, {"saved": False})
            self.assertEqual(app_state.load_json(path, {}), {"saved": True})
            self.assertEqual(list(Path(folder).glob("*.tmp")), [])

    def test_damaged_file_is_reported_and_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.json"
            path.write_bytes(b'{"unfinished":')
            with self.assertRaisesRegex(app_state.StateFileError, "preserved"):
                app_state.load_json(path, {})
            with self.assertRaises(app_state.StateFileError):
                app_state.save_json(path, {"new": True})
            self.assertEqual(path.read_bytes(), b'{"unfinished":')
            self.assertEqual(app_state.load_json(Path(folder) / "missing.json", {}), {})

    def test_process_updates_preserve_all_fields_and_totals(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.json"
            app_state.save_json(path, {})
            context = multiprocessing.get_context("spawn")
            processes = [context.Process(target=increment_saved_state, args=(str(path), f"worker{n}"))
                         for n in range(4)]
            try:
                for process in processes:
                    process.start()
                previous_total = 0
                deadline = time.monotonic() + 20
                while any(process.is_alive() for process in processes) and time.monotonic() < deadline:
                    snapshot = app_state.load_json(path, {})
                    self.assertGreaterEqual(snapshot.get("total", 0), previous_total)
                    previous_total = snapshot.get("total", 0)
                    time.sleep(0.002)
                for process in processes:
                    process.join(20)
                    self.assertEqual(process.exitcode, 0)
                self.assertEqual(app_state.load_json(path, {}), {
                    "total": 80, **{f"worker{n}": 20 for n in range(4)}})
            finally:
                for process in processes:
                    if process.is_alive():
                        process.terminate()
                        process.join()

    def test_terminated_writer_preserves_file_and_releases_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.json"
            app_state.save_json(path, {"value": "old"})
            context = multiprocessing.get_context("spawn")
            ready = context.Event()
            process = context.Process(target=interrupt_before_replace, args=(str(path), ready))
            process.start()
            try:
                self.assertTrue(ready.wait(5))
            finally:
                process.terminate()
                process.join(5)
            self.assertEqual(app_state.load_json(path, {}), {"value": "old"})
            app_state.save_json(path, {"value": "recovered"})
            self.assertEqual(app_state.load_json(path, {}), {"value": "recovered"})


class AppStateMigrationTests(unittest.TestCase):
    def test_legacy_user_data_is_copied_and_paths_are_rewritten(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            legacy_app = root / "old" / "app"
            legacy_repo = root / "old"
            data_dir = root / "local-data"
            legacy_app.mkdir(parents=True)
            (legacy_repo / "data").mkdir()
            (legacy_app / "state" / "backups").mkdir(parents=True)
            (legacy_app / "obs_text").mkdir()
            (legacy_app / "crop_screenshots").mkdir()
            (legacy_app / "sync_screenshots").mkdir()

            runner_file = legacy_app / "runners.csv"
            runner_file.write_text("display_name,twitch_name\nRunner,runner\n", encoding="utf-8")
            config = {
                "runner_csv": str(runner_file),
                "obs_text_dir": str(legacy_app / "obs_text"),
                "screenshot_dir": str(legacy_app / "crop_screenshots"),
                "obs_websocket": {"host": "localhost", "port": 4455, "password": "secret"},
            }
            (legacy_app / "app_config.json").write_text(json.dumps(config), encoding="utf-8")
            (legacy_app / "state" / "crop_presets.json").write_text('{"saved": true}', encoding="utf-8")
            (legacy_app / "state" / "layout_designer.json").write_text('{"layout": "2P"}', encoding="utf-8")
            (legacy_app / "state" / "media_scene_items.json").write_text('{"version": 2}', encoding="utf-8")
            (legacy_app / "state" / "backups" / "runners.csv").write_text("backup", encoding="utf-8")
            (legacy_app / "state" / "restream_app.log").write_text("transient", encoding="utf-8")
            (legacy_app / "obs_text" / "runner1.txt").write_text("Runner", encoding="utf-8")
            (legacy_app / "crop_screenshots" / "crop.png").write_bytes(b"crop")
            (legacy_app / "sync_screenshots" / "sync.png").write_bytes(b"sync")
            (legacy_app / "race_setup_last.txt").write_text("2P", encoding="utf-8")

            migrated = app_state.migrate_legacy_data(legacy_app, legacy_repo, data_dir)

            self.assertTrue(migrated)
            self.assertEqual((data_dir / "runners.csv").read_text(encoding="utf-8"), runner_file.read_text(encoding="utf-8"))
            self.assertTrue((data_dir / "state" / "crop_presets.json").exists())
            self.assertTrue((data_dir / "state" / "layout_designer.json").exists())
            self.assertTrue((data_dir / "state" / "media_scene_items.json").exists())
            self.assertTrue((data_dir / "state" / "backups" / "runners.csv").exists())
            self.assertFalse((data_dir / "state" / "restream_app.log").exists())
            self.assertTrue((data_dir / "obs_text" / "runner1.txt").exists())
            self.assertTrue((data_dir / "crop_screenshots" / "crop.png").exists())
            self.assertTrue((data_dir / "sync_screenshots" / "sync.png").exists())
            self.assertTrue((data_dir / "race_setup_last.txt").exists())
            self.assertTrue(runner_file.exists(), "Migration must leave the old installation untouched")

            migrated_config = json.loads((data_dir / "app_config.json").read_text(encoding="utf-8"))
            self.assertEqual(migrated_config["runner_csv"], str(data_dir / "runners.csv"))
            self.assertEqual(migrated_config["obs_text_dir"], str(data_dir / "obs_text"))
            self.assertEqual(migrated_config["screenshot_dir"], str(data_dir / "crop_screenshots"))
            self.assertEqual(migrated_config["obs_websocket"]["password"], "secret")

    def test_existing_destination_files_are_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            legacy = root / "old"
            data_dir = root / "local-data"
            legacy.mkdir()
            data_dir.mkdir()
            (legacy / "runners.csv").write_text("old", encoding="utf-8")
            (data_dir / "runners.csv").write_text("current", encoding="utf-8")

            app_state.migrate_legacy_data(legacy, legacy, data_dir)

            self.assertEqual((data_dir / "runners.csv").read_text(encoding="utf-8"), "current")

    def test_new_install_seeds_example_runner_list(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            legacy = root / "empty-install"
            data_dir = root / "local-data"
            seed = root / "example-runners.csv"
            legacy.mkdir()
            seed.write_text("display_name,twitch_name\nExample,example\n", encoding="utf-8")

            app_state.migrate_legacy_data(legacy, legacy, data_dir, seed)

            self.assertEqual((data_dir / "runners.csv").read_text(encoding="utf-8"), seed.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
