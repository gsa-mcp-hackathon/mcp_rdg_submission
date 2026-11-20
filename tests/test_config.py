import os
import unittest
from unittest.mock import patch

from mcp_rdg.config import Settings


class SettingsTests(unittest.TestCase):
    def test_reads_and_normalizes_environment(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DATABRICKS_HOST": "https://workspace.example.com/",
                "DATABRICKS_HTTP_PATH": "/sql/1.0/warehouses/example",
                "DATABRICKS_TOKEN": "test-token",
                "MCP_RDG_MAX_PREVIEW_ROWS": "25",
            },
            clear=True,
        ):
            settings = Settings.from_env()

        self.assertEqual(settings.server_hostname, "workspace.example.com")
        self.assertEqual(settings.max_preview_rows, 25)

    def test_reports_all_missing_required_values(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(
                ValueError,
                "DATABRICKS_HOST, DATABRICKS_HTTP_PATH, DATABRICKS_TOKEN",
            ):
                Settings.from_env()

    def test_rejects_preview_limit_outside_safe_range(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DATABRICKS_HOST": "workspace.example.com",
                "DATABRICKS_HTTP_PATH": "/warehouse",
                "DATABRICKS_TOKEN": "test-token",
                "MCP_RDG_MAX_PREVIEW_ROWS": "1001",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "between 1 and 1000"):
                Settings.from_env()


if __name__ == "__main__":
    unittest.main()

