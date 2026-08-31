from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

from PIL import Image


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

import stream_syncer  # noqa: E402


class StreamSyncerPreviewTests(unittest.TestCase):
    def test_direct_two_player_preview_keeps_complete_obs_frame(self) -> None:
        panel = types.SimpleNamespace(is_media_feed_mode=lambda: True)
        image = Image.new("RGB", (1920, 1080))

        result = stream_syncer.SyncPanel.crop_timer_preview_image(
            panel,
            image,
            [1, 2],
            "2P",
        )

        self.assertIs(result, image)
        self.assertEqual(result.size, (1920, 1080))


if __name__ == "__main__":
    unittest.main()
