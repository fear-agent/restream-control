from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import update_service


class UpdateServiceTests(unittest.TestCase):
    def test_release_assets_match_zip_and_checksum(self) -> None:
        payload = {
            "tag_name": "v0.3.1",
            "html_url": "https://github.com/example/releases/v0.3.1",
            "assets": [
                {"name": "RestreamControl-v0.3.1.zip.sha256", "browser_download_url": "https://example/hash"},
                {"name": "RestreamControl-v0.3.1.zip", "browser_download_url": "https://example/zip"},
            ],
        }
        self.assertEqual(
            update_service.select_release_assets(payload),
            ("v0.3.1", payload["html_url"], "https://example/zip", "https://example/hash"),
        )

    def test_verified_archive_extracts_packaged_app(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "update.zip"
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("Restream Control.exe", b"exe")
                output.writestr("apply_update.ps1", b"helper")
                output.writestr("assets/logo.png", b"asset")
            checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
            package = update_service.extract_verified_package(archive, checksum, root / "staged")
            self.assertTrue((package / "Restream Control.exe").is_file())

    def test_archive_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "update.zip"
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("Restream Control.exe", b"exe")
                output.writestr("apply_update.ps1", b"helper")
                output.writestr("../outside.txt", b"bad")
            checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
            with self.assertRaisesRegex(RuntimeError, "Unsafe path"):
                update_service.extract_verified_package(archive, checksum, root / "staged")
            self.assertFalse((root / "outside.txt").exists())

    def test_bad_checksum_is_rejected_before_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "update.zip"
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("Restream Control.exe", b"exe")
                output.writestr("apply_update.ps1", b"helper")
            with self.assertRaisesRegex(RuntimeError, "failed SHA-256"):
                update_service.extract_verified_package(archive, "0" * 64, root / "staged")


if __name__ == "__main__":
    unittest.main()
