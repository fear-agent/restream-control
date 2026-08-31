import sys
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
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


if __name__ == "__main__":
    unittest.main()
