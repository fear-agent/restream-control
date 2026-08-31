import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


APP_DIR = Path(__file__).resolve().parents[1] / "app"
os.environ.setdefault("RESTREAM_CONTROL_DATA_DIR", tempfile.mkdtemp(prefix="restream-control-tests-"))
sys.path.insert(0, str(APP_DIR))

import restream_app  # noqa: E402


class LayoutGeometryTests(unittest.TestCase):
    def test_release_version_is_0_3_0(self) -> None:
        self.assertEqual(restream_app.APP_VERSION, "0.3.0")

    def test_preferred_direct_quality_includes_uncommon_native_sizes(self) -> None:
        qualities = restream_app.PREFERRED_DIRECT_QUALITY.split(",")

        self.assertLess(qualities.index("576p"), qualities.index("480p"))
        self.assertLess(qualities.index("540p"), qualities.index("480p"))

    def test_layout_geometry_reports_obs_style_edge_distances(self) -> None:
        geometry = restream_app.layout_geometry({"x": 289, "y": 545, "w": 603, "h": 488})

        self.assertEqual(
            geometry,
            {
                "x": 289,
                "y": 545,
                "w": 603,
                "h": 488,
                "left": 289,
                "top": 545,
                "right": 1028,
                "bottom": 47,
            },
        )

    def test_layout_geometry_rounds_shared_edges_consistently(self) -> None:
        geometry = restream_app.layout_geometry({"x": 100.4, "y": 200.4, "w": 300.4, "h": 400.4})

        self.assertEqual(geometry["x"] + geometry["w"] + geometry["right"], restream_app.DESIGN_WIDTH)
        self.assertEqual(geometry["y"] + geometry["h"] + geometry["bottom"], restream_app.DESIGN_HEIGHT)

    def test_existing_obs_text_source_is_repointed_to_shared_data(self) -> None:
        calls: list[tuple[str, dict, bool]] = []

        class FakeClient:
            def get_input_settings(self, source_name: str) -> dict:
                if source_name != "Runner 1 Name":
                    raise RuntimeError("not found")
                return {"inputSettings": {"read_from_file": True, "file": "C:/old/obs_text/runner1.txt"}}

            def set_input_settings(self, source_name: str, settings: dict, overlay: bool) -> None:
                calls.append((source_name, settings, overlay))

        panel = types.SimpleNamespace(
            obs_response_value=lambda obj, *names, default=None: next(
                (obj[name] for name in names if isinstance(obj, dict) and name in obj),
                default,
            )
        )
        with (
            mock.patch.object(restream_app.obs_crop_service, "connect", return_value=FakeClient()),
            mock.patch.object(restream_app.app_state, "load_config", return_value={"obs_source_map": {}}),
        ):
            repaired = restream_app.RestreamApp.repair_obs_text_file_paths(panel)

        self.assertEqual(repaired, 1)
        self.assertEqual(calls[0][0], "Runner 1 Name")
        self.assertEqual(calls[0][1]["file"], str((restream_app.OBS_TEXT_DIR / "runner1.txt").resolve()))


if __name__ == "__main__":
    unittest.main()
