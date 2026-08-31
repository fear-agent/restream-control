from __future__ import annotations

import io
import os
import socket
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


APP_DIR = Path(__file__).resolve().parents[1] / "app"
os.environ.setdefault("RESTREAM_CONTROL_DATA_DIR", tempfile.mkdtemp(prefix="restream-control-tests-"))
sys.path.insert(0, str(APP_DIR))

import media_feed_service  # noqa: E402


class MediaFeedServiceTests(unittest.TestCase):
    def test_stream_activity_uses_only_latest_runner_session(self) -> None:
        log = io.BytesIO(
            b"[cli][info] Stream not available, will re-fetch streams in 10 sec\n"
            b"[2026-08-30T18:09:18] Starting runner, attempt 1, mode=Stable, delay=0s\n"
            b"[cli][info] Got HTTP request from Lavf/62.12.102\n"
            b"[cli][info] Opening stream: 720p60 (hls)\n"
        )
        with mock.patch.object(Path, "open", return_value=log):
            self.assertEqual(media_feed_service.stream_activity(1), "playing")

    def test_stream_activity_reports_ended_current_stream(self) -> None:
        log = io.BytesIO(
            b"[2026-08-30T18:09:18] Starting runner, attempt 1, mode=Stable, delay=0s\n"
            b"[cli][info] Opening stream: 720p60 (hls)\n"
            b"[cli][info] Stream not available, will re-fetch streams in 10 sec\n"
        )
        with mock.patch.object(Path, "open", return_value=log):
            self.assertEqual(media_feed_service.stream_activity(1), "offline")

    def test_stream_activity_reports_unknown_before_obs_requests_video(self) -> None:
        log = io.BytesIO(
            b"[2026-08-30T18:09:18] Starting runner, attempt 1, mode=Stable, delay=0s\n"
            b"[cli][info] Starting server, access with one of:\n"
            b"[cli][info] Got HTTP request from Lavf/62.12.102\n"
        )
        with mock.patch.object(Path, "open", return_value=log):
            self.assertEqual(media_feed_service.stream_activity(1), "unknown")

    def test_obs_url_is_layout_specific_loopback_http(self) -> None:
        self.assertEqual(media_feed_service.feed_source_url(1, "4P"), "http://127.0.0.1:5001/")
        self.assertEqual(media_feed_service.feed_source_url(1, "2P"), "http://127.0.0.1:5101/")

    def test_streamlink_command_serves_persistent_local_http(self) -> None:
        command = media_feed_service.streamlink_command("runner", "720p", "Stable", 5101)
        self.assertIn("--player-external-http", command)
        self.assertIn("--player-external-http-continuous", command)
        self.assertIn("--retry-open", command)
        self.assertNotIn("--stdout", command)
        self.assertNotIn("ffmpeg", command)
        self.assertEqual(command[-2:], ["https://twitch.tv/runner", "720p"])
        port_index = command.index("--player-external-http-port")
        self.assertEqual(command[port_index + 1], "5101")

    def test_wait_for_http_server_detects_listener(self) -> None:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)

        class FakeProcess:
            @staticmethod
            def poll() -> None:
                return None

        try:
            self.assertTrue(
                media_feed_service.wait_for_http_server(
                    FakeProcess(),
                    listener.getsockname()[1],
                    timeout=0.5,
                )
            )
        finally:
            listener.close()

    def test_direct_prerequisites_do_not_require_ffmpeg(self) -> None:
        with mock.patch.object(
            media_feed_service,
            "command_available",
            side_effect=lambda name: name == "streamlink",
        ):
            self.assertEqual(media_feed_service.prereq_errors(), [])

    def test_running_feed_delay_uses_obs_filter_without_starting_worker(self) -> None:
        state = {
            "status": "running",
            "worker_pid": 123,
            "twitch_name": "runner",
            "display_name": "Runner",
            "delay_seconds": 0,
            "layout": "2P",
        }
        with (
            mock.patch.object(media_feed_service, "load_state", return_value=state),
            mock.patch.object(media_feed_service, "is_worker_running", return_value=True),
            mock.patch.object(media_feed_service, "set_obs_sync_delay") as set_delay,
            mock.patch.object(media_feed_service, "write_state") as write_state,
        ):
            media_feed_service.restart_slot_with_delay(2, 3.5)

        set_delay.assert_called_once_with(2, "2P", 3.5)
        write_state.assert_called_once()

    def test_obs_sync_delay_creates_native_async_filter(self) -> None:
        calls: list[tuple] = []

        class FakeResponse:
            filters: list[dict] = []

        class FakeClient:
            def get_source_filter_list(self, source_name: str) -> FakeResponse:
                calls.append(("list", source_name))
                return FakeResponse()

            def create_source_filter(
                self,
                source_name: str,
                filter_name: str,
                filter_kind: str,
                settings: dict,
            ) -> None:
                calls.append(("create", source_name, filter_name, filter_kind, settings))

        fake_module = types.SimpleNamespace(connect=lambda: FakeClient())
        with mock.patch.dict(sys.modules, {"obs_crop_service": fake_module}):
            media_feed_service.set_obs_sync_delay(1, "2P", 5.08)

        self.assertEqual(
            calls[-1],
            (
                "create",
                "2P R1 Media Stream",
                media_feed_service.SYNC_FILTER_NAME,
                "async_delay_filter",
                {"delay_ms": 5080},
            ),
        )

    def test_obs_sync_delay_rejects_more_than_twenty_seconds(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "up to 20 seconds"):
            media_feed_service.set_obs_sync_delay(1, "2P", 20.001)

    def test_obs_receiver_restart_uses_restart_action(self) -> None:
        actions: list[tuple[str, str]] = []

        class FakeClient:
            def trigger_media_input_action(self, source_name: str, action: str) -> None:
                actions.append((source_name, action))

        fake_module = types.SimpleNamespace(connect=lambda: FakeClient())
        with mock.patch.dict(sys.modules, {"obs_crop_service": fake_module}):
            log = io.StringIO()
            media_feed_service.restart_obs_receiver(2, "2P", log)

        self.assertEqual(
            actions,
            [
                ("2P R2 Media Stream", "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_RESTART"),
            ],
        )

    def test_obs_receiver_stop_uses_stop_action(self) -> None:
        actions: list[tuple[str, str]] = []

        class FakeClient:
            def trigger_media_input_action(self, source_name: str, action: str) -> None:
                actions.append((source_name, action))

        fake_module = types.SimpleNamespace(connect=lambda: FakeClient())
        with mock.patch.dict(sys.modules, {"obs_crop_service": fake_module}):
            media_feed_service.stop_obs_receiver(4, "4P")

        self.assertEqual(
            actions,
            [
                ("4P R4 Media Stream", "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_STOP"),
            ],
        )

    def test_obs_video_detection_updates_running_status(self) -> None:
        state = {"status": "running", "latency_mode": "Stable"}
        with (
            mock.patch.object(media_feed_service, "load_state", return_value=state),
            mock.patch.object(media_feed_service, "write_state") as write_state,
        ):
            media_feed_service.set_obs_video_detected(2, True)

        write_state.assert_called_once_with(
            2,
            obs_video_detected=True,
            message="OBS video detected. Streamlink HTTP feed is running in Stable mode.",
        )

    def test_write_state_removes_retired_relay_fields(self) -> None:
        state = {
            "layout": "2P",
            "relay_buffered_bytes": 10,
            "relay_buffered_packets": 2,
            "relay_control_supported": True,
            "relay_delay_seconds": 1.5,
        }
        with (
            mock.patch.object(media_feed_service, "load_state", return_value=state.copy()),
            mock.patch.object(media_feed_service, "port_base", return_value=5101),
            mock.patch.object(media_feed_service.app_state, "save_json") as save_json,
        ):
            media_feed_service.write_state(1, status="running")

        saved = save_json.call_args.args[1]
        self.assertFalse(any(key.startswith("relay_") for key in saved))


if __name__ == "__main__":
    unittest.main()
