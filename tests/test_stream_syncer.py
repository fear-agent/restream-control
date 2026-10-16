from __future__ import annotations

import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

from PIL import Image


APP_DIR = Path(__file__).resolve().parents[1] / "app"
os.environ.setdefault("RESTREAM_CONTROL_DATA_DIR", tempfile.mkdtemp(prefix="restream-control-tests-"))
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

    def test_obs_scene_preview_preserves_every_pixel_for_both_engines(self) -> None:
        image = Image.new("RGB", (1920, 1080))
        for media_mode in (False, True):
            panel = types.SimpleNamespace(is_media_feed_mode=lambda: media_mode)
            for layout in ("2P", "4P"):
                for slots in ([1], [1, 2], [1, 2, 3], [1, 2, 3, 4]):
                    with self.subTest(media_mode=media_mode, layout=layout, slots=slots):
                        result = stream_syncer.SyncPanel.crop_timer_preview_image(
                            panel, image, slots, layout,
                        )
                        self.assertIs(result, image)

    def test_vlc_fallback_grid_rearranges_two_runner_cells(self) -> None:
        image = Image.new("RGB", (208, 144), "black")
        image.paste("red", (0, 0, 100, 68))
        image.paste("blue", (0, 76, 100, 144))
        result = stream_syncer.SyncPanel.crop_timer_preview_image(
            types.SimpleNamespace(), image, [1, 2], "2P", fallback_grid=True,
        )
        self.assertEqual(result.size, (208, 68))
        self.assertEqual(result.getpixel((50, 34)), (255, 0, 0))
        self.assertEqual(result.getpixel((158, 34)), (0, 0, 255))


if __name__ == "__main__":
    unittest.main()
