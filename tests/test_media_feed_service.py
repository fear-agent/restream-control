from __future__ import annotations

import io
import socket
import sys
import types
import unittest
from pathlib import Path
from unittest import mock


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

import media_feed_service  # noqa: E402


class MediaFeedServiceTests(unittest.TestCase):
    def test_obs_url_has_receive_buffers(self) -> None:
        url = media_feed_service.feed_source_url(1, "4P")
        self.assertIn("buffer_size=1048576", url)
        self.assertIn("fifo_size=100000", url)
        self.assertIn("overrun_nonfatal=1", url)

    def test_live_ffmpeg_command_does_not_accelerate_input(self) -> None:
        command = media_feed_service.ffmpeg_command("udp://127.0.0.1:12345?pkt_size=1316")
        self.assertNotIn("-readrate", command)
        self.assertNotIn("-readrate_catchup", command)
        self.assertEqual(command[-3:], ["-f", "mpegts", "udp://127.0.0.1:12345?pkt_size=1316"])

    def test_delayed_ffmpeg_command_uses_the_persistent_relay(self) -> None:
        command = media_feed_service.ffmpeg_command(
            "udp://127.0.0.1:12345?pkt_size=1316",
            4.25,
        )
        self.assertNotIn("fifo", command)
        self.assertNotIn("-timeshift", command)
        self.assertEqual(command[-3:], ["-f", "mpegts", "udp://127.0.0.1:12345?pkt_size=1316"])

    def test_udp_relay_forwards_packets(self) -> None:
        receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        receiver.bind(("127.0.0.1", 0))
        receiver.settimeout(2.0)
        relay = media_feed_service.BufferedUdpRelay(receiver.getsockname()[1], io.StringIO())
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            relay.start()
            payload = bytes(range(188)) * 7
            sender.sendto(payload, ("127.0.0.1", relay.listen_port))
            received, _address = receiver.recvfrom(65536)
            self.assertEqual(received, payload)
            self.assertGreaterEqual(relay.packets, 1)
            self.assertEqual(relay.errors, 0)
        finally:
            sender.close()
            relay.close()
            receiver.close()

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


if __name__ == "__main__":
    unittest.main()
