import copy
import itertools
import os
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import URLError

APP_DIR = Path(__file__).resolve().parents[1] / "app"
os.environ.setdefault("RESTREAM_CONTROL_DATA_DIR", tempfile.mkdtemp(prefix="restream-control-tests-"))
sys.path.insert(0, str(APP_DIR))
import restream_app


def bind(panel, *names):
    for name in names:
        setattr(panel, name, types.MethodType(getattr(restream_app.RestreamApp, name), panel))
    return panel


class UpdateErrorTests(unittest.TestCase):
    def panel(self):
        callbacks = []
        panel = types.SimpleNamespace(
            after=lambda delay, callback, *args: callbacks.append((callback, args)),
            update_check_button=mock.Mock(), update_download_button=mock.Mock(),
            update_status_var=mock.Mock(), update_available_tag="v1", update_download_url="https://example.invalid/app.zip",
            update_checksum_url="https://example.invalid/app.sha256", _handoff_update=mock.Mock(),
        )
        bind(panel, "apply_update_check_error", "_update_prepare_failed")
        return panel, callbacks

    def test_failed_checks_display_error_after_worker_exits_and_restore_button(self):
        for response in (URLError("offline"), "[]", "not json"):
            with self.subTest(response=response):
                panel, callbacks = self.panel()
                connection = mock.Mock()
                connection.__enter__ = mock.Mock(return_value=types.SimpleNamespace(read=lambda: str(response).encode()))
                connection.__exit__ = mock.Mock(return_value=False)
                with mock.patch.object(restream_app, "urlopen", side_effect=response if isinstance(response, Exception) else None,
                                       return_value=connection):
                    restream_app.RestreamApp.check_for_updates_worker(panel)
                for callback, args in callbacks:
                    callback(*args)
                panel.update_check_button.configure.assert_called_with(state="normal")
                self.assertIn("Update check failed:", panel.update_status_var.set.call_args.args[0])

    def test_download_and_verification_errors_restore_install_button(self):
        for step in ("download_file", "extract_verified_package"):
            with self.subTest(step=step), tempfile.TemporaryDirectory() as folder:
                panel, callbacks = self.panel()
                (Path(folder) / "update.zip.sha256").write_text("0" * 64)
                with (
                    mock.patch.object(restream_app.update_service, "new_transaction_dir", return_value=Path(folder)),
                    mock.patch.object(restream_app.update_service, "download_file") as download,
                    mock.patch.object(restream_app.update_service, "extract_verified_package") as verify,
                ):
                    (download if step == "download_file" else verify).side_effect = RuntimeError("simulated failure")
                    restream_app.RestreamApp._prepare_update_worker(panel)
                with mock.patch.object(restream_app.messagebox, "showerror"):
                    for callback, args in callbacks:
                        callback(*args)
                panel.update_download_button.configure.assert_called_with(state="normal")
                panel._handoff_update.assert_not_called()
                self.assertIn("simulated failure", panel.update_status_var.set.call_args.args[0])


class LayoutOwnershipTests(unittest.TestCase):
    def test_layer_permutations_preserve_obs_owned_indices(self):
        for desired in itertools.permutations([1, 3, 5]):
            with self.subTest(desired=desired):
                current = [0, 1, 2, 3, 4, 5, 6]
                moves = []
                def move(scene, item_id, index):
                    moves.append(item_id)
                    current.remove(item_id)
                    current.insert(index, item_id)
                client = types.SimpleNamespace(
                    get_scene_item_list=lambda scene: {"sceneItems": [
                        {"sceneItemId": item_id, "sceneItemIndex": index}
                        for index, item_id in enumerate(current)]},
                    set_scene_item_index=move,
                )
                panel = bind(types.SimpleNamespace(), "obs_response_value")
                errors = restream_app.RestreamApp.apply_designer_scene_order(
                    panel, client, "scene", list(desired), {n: n for n in desired})
                self.assertEqual(errors, [])
                self.assertEqual(current, [0, desired[0], 2, desired[1], 4, desired[2], 6])
                self.assertTrue(set(moves) <= {1, 3, 5})

    def test_apply_skips_legacy_decorations_and_keeps_saved_data(self):
        regions = [{"type": kind, "layout": "2P", "source": name, "x": 0, "y": 0, "w": 100, "h": 100}
                   for kind, name in (("Text", "Old text"), ("Image", "Old image"), ("Game", "Game"))]
        data = {"layout": "2P", "regions": regions}
        original = copy.deepcopy(data)
        client = mock.Mock()
        panel = types.SimpleNamespace(
            normalize_layout_region=lambda region: dict(region), save_obs_settings=lambda: True,
            load_obs_template=lambda: {}, supported_obs_input_kinds=lambda client: set(),
            scan_obs_snapshot=lambda client: {"scenes": ["2P Restream"], "all_sources": ["Old text", "Old image", "Game"]},
            designer_scene_name=lambda layout, media: "2P Restream",
            scene_item_map=lambda *args: {"Old text": 1, "Old image": 2, "Game": 3},
            apply_designer_background_to_obs=lambda *args: ("No background", False),
            designer_source_name_for_region=lambda layout, region, media: region["source"],
            layout_region_label=lambda region: region["type"],
            create_designer_source_if_missing=mock.Mock(return_value=(3, "EXISTING")),
            designer_transform_from_region=lambda region: {},
            designer_layer_order_names=mock.Mock(return_value=["Game"]),
            mapped_designer_layer_order_names=lambda names, mapping: names,
            apply_designer_scene_order=mock.Mock(return_value=[]),
            set_builder_text=mock.Mock(), builder_status_var=mock.Mock(), layout_status_var=mock.Mock(), log_status=mock.Mock(),
        )
        with mock.patch.object(restream_app.obs_crop_service, "connect", return_value=client):
            restream_app.RestreamApp.apply_designer_layout_to_obs(panel, data, ["2P"], confirm=False)
        self.assertEqual(data, original)
        self.assertEqual(panel.create_designer_source_if_missing.call_count, 1)
        self.assertEqual(panel.create_designer_source_if_missing.call_args.args[3]["type"], "Game")
        self.assertEqual([r["type"] for r in panel.designer_layer_order_names.call_args.args[1]], ["Game"])
        client.set_scene_item_transform.assert_called_once_with("2P Restream", 3, {})

    def test_cleanup_does_not_claim_retired_text_sources(self):
        panel = types.SimpleNamespace(media_source_name=lambda layout, slot, part: f"{layout} R{slot} Media {part}")
        candidates = restream_app.RestreamApp.cleanup_candidate_layout_sources(panel, "2P")
        self.assertNotIn("2P Text 1", candidates)
        self.assertNotIn("2P Image 1", candidates)
        self.assertIn("Runner 1 Name", candidates)
        self.assertIn("Background 2P", candidates)


class BackgroundWorkTests(unittest.TestCase):
    def test_launch_context_allows_empty_unrelated_runner_rows(self):
        field = lambda value: types.SimpleNamespace(get=lambda: value)
        panel = types.SimpleNamespace(
            **{name: field(value) for name, value in {
                "mode_var": "4", "playback_engine_var": "VLC Windows", "replace_slot_var": "1",
                "media_feed_quality_var": "Preferred", "media_feed_latency_var": "Stable",
            }.items()},
            runner_rows={1: types.SimpleNamespace(enabled_var=field(True), selected_var=field(""),
                                                 display_var=field(""), twitch_var=field(""))},
            get_comms=lambda: "",
        )
        context = restream_app.RestreamApp.stream_check_context(panel)
        self.assertEqual(context[1], ((1, True, "", "", ""),))

    def test_status_refresh_discards_snapshot_when_new_refresh_is_requested(self):
        panel = types.SimpleNamespace(
            media_feed_rows_frame=object(), media_feed_refresh_after=None,
            mode_var=types.SimpleNamespace(get=lambda: "4"), run_background=mock.Mock(),
            render_media_feed_snapshot=mock.Mock(),
        )
        bind(panel, "refresh_media_feeds")
        panel.refresh_media_feeds()
        panel.refresh_media_feeds(check_obs_video=True)
        self.assertEqual(panel.run_background.call_count, 1)
        panel.run_background.call_args.args[1](({}, {}, {}))
        panel.render_media_feed_snapshot.assert_not_called()
        self.assertEqual(panel.run_background.call_count, 2)
        panel.run_background.call_args.args[1](({}, {}, {}))
        panel.render_media_feed_snapshot.assert_called_once_with(4, {}, {}, {})

    def test_four_checks_overlap_and_keep_runner_associations(self):
        barrier = threading.Barrier(4)
        def check(name):
            barrier.wait(timeout=3)
            return name != "runner2", "offline"
        panel = types.SimpleNamespace(check_twitch_stream_available=check)
        runners = {n: types.SimpleNamespace(display_name=f"R{n}", twitch_name=f"runner{n}") for n in range(1, 5)}
        available, errors = restream_app.RestreamApp.partition_available_streams(panel, runners, range(1, 5))
        self.assertEqual(available, [1, 3, 4])
        self.assertEqual(errors, ["Runner 2 R2: offline"])

    def test_slow_worker_leaves_tk_callbacks_on_main_thread(self):
        callbacks = []
        release = threading.Event()
        main_thread = threading.get_ident()
        panel = types.SimpleNamespace(after=lambda delay, callback: callbacks.append(callback))
        complete = mock.Mock()
        failed = mock.Mock()
        restream_app.RestreamApp.run_background(panel, lambda: (release.wait(3), threading.get_ident()), complete, failed)
        callbacks.pop(0)()
        complete.assert_not_called()
        release.set()
        deadline = time.monotonic() + 3
        while not complete.called and time.monotonic() < deadline:
            callbacks.pop(0)()
            time.sleep(0.005)
        failed.assert_not_called()
        self.assertNotEqual(complete.call_args.args[0][1], main_thread)

    def test_duplicate_and_changed_setup_cannot_launch(self):
        for changed in (False, True):
            with self.subTest(changed=changed):
                panel = types.SimpleNamespace(stream_check_context=mock.Mock(return_value="original"),
                                              log_status=mock.Mock(), run_background=mock.Mock())
                continuation = mock.Mock()
                restream_app.RestreamApp.check_streams_then(panel, {}, [], continuation)
                restream_app.RestreamApp.check_streams_then(panel, {}, [], continuation)
                self.assertEqual(panel.run_background.call_count, 1)
                if changed:
                    panel.stream_check_context.return_value = "edited"
                panel.run_background.call_args.args[1](([1], []))
                self.assertEqual(continuation.call_count, 0 if changed else 1)
                self.assertIsNone(panel._stream_check_token)


class RedrawTests(unittest.TestCase):
    def test_background_resize_is_reused_until_size_or_image_changes(self):
        source = mock.Mock()
        panel = types.SimpleNamespace(layout_bg_source=source)
        with mock.patch.object(restream_app.ImageTk, "PhotoImage", side_effect=lambda image: object()):
            first = restream_app.RestreamApp.layout_background_photo(panel, 960, 540)
            for _ in range(100):
                self.assertIs(restream_app.RestreamApp.layout_background_photo(panel, 960, 540), first)
            source.resize.assert_called_once()
            self.assertIsNot(restream_app.RestreamApp.layout_background_photo(panel, 1920, 1080), first)
            self.assertEqual(source.resize.call_count, 2)
            panel.layout_bg_source = mock.Mock()
            restream_app.RestreamApp.layout_background_photo(panel, 1920, 1080)
            panel.layout_bg_source.resize.assert_called_once()

    def test_drag_requests_are_coalesced(self):
        panel = types.SimpleNamespace(after=mock.Mock(return_value="scheduled"), draw_layout_designer=mock.Mock())
        for _ in range(100):
            restream_app.RestreamApp.redraw_layout_designer(panel)
        panel.after.assert_called_once_with(16, panel.draw_layout_designer)


if __name__ == "__main__":
    unittest.main()
