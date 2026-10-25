"""Guard package discovery against stale release artifacts and package renames."""

import tempfile
import unittest
from pathlib import Path

from verify_isolated_wheels import discover_packages


class PackageDiscoveryTest(unittest.TestCase):
    def test_uses_manifest_versions_and_import_roots_instead_of_stale_dist(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text(
                '[tool.uv.workspace]\nmembers = ["sentinel", "reporter"]\n'
            )
            for name, version, module in (
                ("sentinel", "0.2.0", "atlas_richie.sentinel"),
                ("reporter", "0.1.0", "atlas_richie.sentinel_reporter_rules"),
            ):
                project = root / name
                project.mkdir()
                (project / "pyproject.toml").write_text(
                    f'[project]\nname = "atlas-richie-{name}"\nversion = "{version}"\n'
                    f'[tool.uv.build-backend]\nmodule-name = "{module}"\n'
                )
            (root / "dist").mkdir()
            (root / "dist" / "obsolete-99.0.whl").touch()
            self.assertEqual(
                discover_packages(root),
                (
                    ("atlas-richie-sentinel==0.2.0", ("atlas_richie.sentinel",)),
                    (
                        "atlas-richie-reporter==0.1.0",
                        ("atlas_richie.sentinel_reporter_rules",),
                    ),
                ),
            )

    def test_missing_workspace_member_fails_instead_of_silently_skipping(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text(
                '[tool.uv.workspace]\nmembers = ["missing"]\n'
            )
            with self.assertRaises(FileNotFoundError):
                discover_packages(root)

    def test_empty_workspace_cannot_report_a_successful_release_check(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_text("[tool.uv.workspace]\nmembers = []\n")
            with self.assertRaisesRegex(ValueError, "no distributions"):
                discover_packages(root)


if __name__ == "__main__":
    unittest.main()
