import unittest
from datetime import datetime, timezone
from decimal import Decimal

from mcp_rdg.config import Settings
from mcp_rdg.databricks import DatabricksGateway, quote_identifier


class FakeCursor:
    description = (("name",), ("value",), ("created_at",))

    def __init__(self) -> None:
        self.statement = ""
        self.closed = False

    def execute(self, statement: str) -> None:
        self.statement = statement

    def fetchall(self) -> list[tuple[object, ...]]:
        return [
            (
                "sample",
                Decimal("1.20"),
                datetime(2026, 1, 2, tzinfo=timezone.utc),
            )
        ]

    def close(self) -> None:
        self.closed = True


class FakeConnection:
    def __init__(self) -> None:
        self.cursor_instance = FakeCursor()
        self.closed = False

    def cursor(self) -> FakeCursor:
        return self.cursor_instance

    def close(self) -> None:
        self.closed = True


class GatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = FakeConnection()
        self.connect_args: dict[str, str] = {}

        def connect(**kwargs: str) -> FakeConnection:
            self.connect_args = kwargs
            return self.connection

        self.gateway = DatabricksGateway(
            Settings("workspace.example.com", "/warehouse", "test-token", 50),
            connect=connect,
        )

    def test_quotes_identifiers(self) -> None:
        self.assertEqual(quote_identifier("odd`name"), "`odd``name`")
        with self.assertRaises(ValueError):
            quote_identifier("")

    def test_lists_tables_in_quoted_namespace_and_closes_resources(self) -> None:
        rows = self.gateway.list_tables("rdg", "public data")

        self.assertEqual(
            self.connection.cursor_instance.statement,
            "SHOW TABLES IN `rdg`.`public data`",
        )
        self.assertEqual(self.connect_args["server_hostname"], "workspace.example.com")
        self.assertTrue(self.connection.cursor_instance.closed)
        self.assertTrue(self.connection.closed)
        self.assertEqual(rows[0]["value"], "1.20")
        self.assertEqual(rows[0]["created_at"], "2026-01-02T00:00:00+00:00")

    def test_previews_only_within_configured_limit(self) -> None:
        self.gateway.preview_table("rdg", "products", "prices", 50)
        self.assertEqual(
            self.connection.cursor_instance.statement,
            "SELECT * FROM `rdg`.`products`.`prices` LIMIT 50",
        )

        with self.assertRaisesRegex(ValueError, "between 1 and 50"):
            self.gateway.preview_table("rdg", "products", "prices", 51)


if __name__ == "__main__":
    unittest.main()

