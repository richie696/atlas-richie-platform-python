from pathlib import Path
import unittest

from atlas_richie.sentinel_console.infrastructure.persistence import (
    setup_window_configuration,
    setup_window_file_store,
)

_PATH_ENV = "SENTINEL_CONSOLE_SETUP_WINDOW_PATH"


class SetupWindowConfigurationTests(unittest.TestCase):
    _configuration_type = setup_window_configuration.SetupWindowConfiguration

    def test_environment_creates_explicit_file_adapter(self) -> None:
        configuration = (
            self._configuration_type.from_environment(
                {_PATH_ENV: "/var/lib/sentinel/setup-window.json"}
            )
        )

        self.assertEqual(
            configuration.path, Path("/var/lib/sentinel/setup-window.json")
        )
        self.assertIsInstance(
            configuration.create_store(), setup_window_file_store.SetupWindowFileStore
        )

    def test_missing_or_invalid_path_fails_closed(self) -> None:
        for environment in ({}, {_PATH_ENV: ""}, {_PATH_ENV: "relative/state.json"}):
            with self.subTest(environment=environment):
                with self.assertRaises(
                    setup_window_configuration.SetupWindowConfigurationError
                ):
                    self._configuration_type.from_environment(environment)

    def test_constructor_rejects_directory_root_and_non_path_values(self) -> None:
        for path in (Path("/"), Path("."), "not-a-path"):
            with self.subTest(path=path):
                with self.assertRaises(
                    setup_window_configuration.SetupWindowConfigurationError
                ):
                    self._configuration_type(path)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
