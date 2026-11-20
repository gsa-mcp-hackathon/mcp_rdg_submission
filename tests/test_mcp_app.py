import asyncio
import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfoNotFoundError

import pandas as pd


SERVER_DIR = Path(__file__).resolve().parents[1] / "mcp_server"
sys.path.insert(0, str(SERVER_DIR))
try:
    import app
    import database
    import exposure
    import fema
    import obligation_queries
    import obligation_tools
    import helpers
finally:
    sys.path.pop(0)


class MCPAppTests(unittest.TestCase):
    def test_registered_tools(self):
        tools = asyncio.run(app.mcp.list_tools())
        self.assertEqual(
            [tool.name for tool in tools],
            [
                "describe_obligations_table",
                "list_distinct_values",
                "search_obligations",
                "get_obligation",
                "summarize_obligations",
                "summarize_pfd_obligations_by_state",
                "summarize_pfd_obligations_by_program",
                "summarize_pfd_obligations_by_naics",
                "summarize_pfd_obligations_by_state_and_naics",
                "summarize_pfd_obligations_by_state_and_county",
                "search_fema_disasters",
                "get_fema_designated_areas",
                "assess_investment_exposure_to_fema_areas",
                "get_current_date",
                "get_current_fiscal_year",
            ],
        )
        exposure = next(
            tool for tool in tools
            if tool.name == "assess_investment_exposure_to_fema_areas"
        )
        self.assertEqual(
            exposure.inputSchema["required"],
            ["disaster_number", "state", "portfolio_group"],
        )
        self.assertIn("does not represent unpaid principal", exposure.description)

    def test_current_date(self):
        instant = datetime.fromisoformat("2026-10-01T00:30:00+00:00")
        for timezone_name, expected_date in [
            ("UTC", "2026-10-01"),
            ("America/New_York", "2026-09-30"),
        ]:
            with self.subTest(timezone=timezone_name):
                with patch.object(helpers, "datetime") as clock:
                    clock.now.side_effect = lambda zone: instant.astimezone(zone)
                    result = asyncio.run(
                        helpers.get_current_date() if timezone_name == "UTC"
                        else helpers.get_current_date(timezone_name)
                    )
                self.assertEqual(result, expected_date)
                self.assertEqual(clock.now.call_args.args[0].key, timezone_name)

    def test_current_fiscal_year(self):
        for timestamp, timezone_name, expected_date, expected_year in [
            ("2026-09-30T12:00:00+00:00", "UTC", "2026-09-30", 2026),
            ("2026-10-01T00:30:00+00:00", "UTC", "2026-10-01", 2027),
            ("2026-10-01T00:30:00+00:00", "America/New_York", "2026-09-30", 2026),
            ("2027-01-01T12:00:00+00:00", "UTC", "2027-01-01", 2027),
            ("2024-02-29T12:00:00+00:00", "UTC", "2024-02-29", 2024),
        ]:
            with self.subTest(timestamp=timestamp, timezone=timezone_name):
                instant = datetime.fromisoformat(timestamp)
                with patch.object(helpers, "datetime") as clock:
                    clock.now.side_effect = lambda zone: instant.astimezone(zone)
                    result = asyncio.run(
                        helpers.get_current_fiscal_year() if timezone_name == "UTC"
                        else helpers.get_current_fiscal_year(timezone_name)
                    )
                self.assertEqual(result, {
                    "fiscal_year": f"FY {expected_year}",
                    "fiscal_year_number": expected_year,
                    "start_date": f"{expected_year - 1}-10-01",
                    "end_date": f"{expected_year}-09-30",
                    "as_of_date": expected_date,
                    "timezone": timezone_name,
                })

    def test_date_tools_reject_invalid_timezone(self):
        for tool in [helpers.get_current_date, helpers.get_current_fiscal_year]:
            with self.subTest(tool=tool.__name__):
                with self.assertRaises(ZoneInfoNotFoundError):
                    asyncio.run(tool("Invalid/Timezone"))

    def test_health(self):
        response = asyncio.run(app.health(None))
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'"mcp_endpoint":"/mcp"', response.body)

    def test_local_bind_address(self):
        result = subprocess.run(
            [sys.executable, "-c", (
                "import app; assert app.mcp.settings.host == '127.0.0.1'"
            )],
            cwd=SERVER_DIR,
            env={**os.environ, "MCP_HOST": "127.0.0.1"},
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_filters_preserve_parameterization(self):
        queries = obligation_queries
        where, params = queries._build_filters(
            state=" SD ",
            county_fips=[" 46001 ", "46001", "46003"],
            investment_types=["Loan Funds - Direct", "Loan Funds - Direct"],
            text="O'Brien",
        )
        self.assertNotIn("O'Brien", where)
        self.assertEqual(params["text"], "%O'Brien%")
        self.assertEqual(params["state"], "SD")
        self.assertEqual(params["county_fips_0"], "46001")
        self.assertEqual(params["county_fips_1"], "46003")
        self.assertNotIn("county_fips_2", params)
        self.assertIn("1 = 0", queries._build_filters(county_fips=[])[0])

    def test_search_paging(self):
        tools = obligation_tools
        with patch.object(tools, "_query", return_value=[
            {"row_id": "abc", "_total_matches": 8},
            {"row_id": "def", "_total_matches": 8},
        ]) as query:
            result = tools.search_obligations(state="SD", limit=2, offset=1)
        self.assertEqual(result, {
            "items": [{"row_id": "abc"}, {"row_id": "def"}],
            "total_matches": 8, "limit": 2, "offset": 1,
        })
        self.assertIn("LIMIT 2 OFFSET 1", query.call_args.args[0])
        self.assertEqual(query.call_args.args[1], {"state": "SD"})

    def test_aggregate_empty_page(self):
        queries = obligation_queries
        with patch.object(queries, "_query", side_effect=[[], [{"total_groups": 5}]]):
            result = queries._aggregate_obligations(
                "state, SUM(obl_amt) AS total_obligation_amount", "state", offset=10,
            )
        self.assertEqual(result, {"items": [], "total": 5, "limit": 100, "offset": 10})

    def test_fema_lookup(self):
        records = [{"disasterNumber": 1234, "declarationTitle": "STORM"}]
        with patch.object(fema.requests, "get") as get:
            get.return_value.json.return_value = {"DisasterDeclarationsSummaries": records * 2}
            result = fema.search_fema_disasters("sd", "storm", "2026-06-01", "2026-07-31")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["search_criteria"]["state"], "SD")
        self.assertIn("state eq 'SD'", get.call_args.kwargs["params"]["$filter"])
        get.return_value.raise_for_status.assert_called_once()

    def test_exposure_county_and_statewide(self):
        for area, expected_fips in [("Example County", ["46001"]), ("Statewide", None)]:
            with self.subTest(area=area):
                areas = pd.DataFrame([{
                    "designatedArea": area, "fipsStateCode": 46, "fipsCountyCode": 1,
                }])
                source_url = "https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries?disasterNumber=1234"
                with (
                    patch.object(exposure, "get_disaster_areas", return_value=(areas, source_url)),
                    patch.object(exposure, "_get_obligation_total", side_effect=[
                        {"total_obligation_amount": 100, "source_row_count": 10},
                        {"total_obligation_amount": 25, "source_row_count": 2},
                    ]) as total,
                    patch.object(exposure, "_get_obligation_county_detail", return_value=[]) as detail,
                ):
                    result = exposure.assess_investment_exposure_to_fema_areas(1234, "sd", "Commercial")
                self.assertEqual(result["fema_area_share_of_statewide_obligations"], 0.25)
                self.assertEqual(result["sources"]["fema_designated_areas_api_url"], source_url)
                self.assertIn(source_url, result["sources"]["fema_attribution_text"])
                self.assertEqual(total.call_args.kwargs["county_fips"], expected_fips)
                self.assertEqual(detail.call_count, int(expected_fips is not None))

    def test_database_query_serialization(self):
        with (
            patch.object(database, "_cfg"),
            patch.object(database, "_hostname", return_value="workspace.example.com"),
            patch.object(database, "_http_path", return_value="/sql/1.0/warehouses/test"),
            patch.object(database.sql, "connect") as connect,
        ):
            connection = connect.return_value.__enter__.return_value
            cursor = connection.cursor.return_value.__enter__.return_value
            cursor.description = [("amount",), ("created",)]
            cursor.fetchall.return_value = [(Decimal("12.50"), date(2026, 6, 1))]
            result = database._query("SELECT :amount, :created", {"amount": 12.5})
        self.assertEqual(result, [{"amount": 12.5, "created": "2026-06-01"}])
        cursor.execute.assert_called_once_with("SELECT :amount, :created", {"amount": 12.5})
        connect.return_value.__exit__.assert_called_once()
        connection.cursor.return_value.__exit__.assert_called_once()

    def test_deployment_entry_point(self):
        result = subprocess.run(
            [sys.executable, "-c", (
                "import runpy; from unittest.mock import patch; "
                "from mcp.server.fastmcp import FastMCP; "
                "runner = patch.object(FastMCP, 'run'); mocked = runner.start(); "
                "runpy.run_path('app.py', run_name='__main__'); "
                "mocked.assert_called_once_with(transport='streamable-http')"
            )],
            cwd=SERVER_DIR,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()