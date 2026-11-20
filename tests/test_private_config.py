import ast
import contextlib
import io
import json
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[1]


def notebook_sources(path):
    notebook = json.loads(path.read_text(encoding="utf-8"))
    for cell in notebook["cells"]:
        source = cell["source"]
        if isinstance(source, list):
            source = "".join(source) if any(line.endswith("\n") for line in source) else "\n".join(source)
        yield cell["cell_type"], source


class PrivateConfigurationTests(unittest.TestCase):
    def test_chat_requires_explicit_mcp_url(self):
        tree = ast.parse((ROOT / "chat_app" / "app.py").read_text(encoding="utf-8"))
        assignment = next(
            node for node in tree.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "MCP_SERVER_URL" for target in node.targets)
        )
        for environment, expected in [({}, ""), ({"MCP_SERVER_URL": " https://example.com/mcp "}, "https://example.com/mcp")]:
            actual = eval(compile(ast.Expression(assignment.value), "<config>", "eval"),
                          {"os": type("Environment", (), {"environ": environment})})
            self.assertEqual(actual, expected)
        self.assertIn("st.stop()", (ROOT / "chat_app" / "app.py").read_text(encoding="utf-8"))

    def test_hosted_url_is_resource_bound(self):
        manifest = (ROOT / "chat_app" / "app.yaml").read_text(encoding="utf-8")
        self.assertIn("valueFrom: mcp-server-url", manifest)
        self.assertNotIn("https://", manifest)

    def test_notebooks_have_no_saved_outputs(self):
        for path in ROOT.glob("*.ipynb"):
            with self.subTest(notebook=path.name):
                notebook = json.loads(path.read_text(encoding="utf-8"))
                for cell in notebook["cells"]:
                    self.assertFalse(cell.get("outputs", []))

    def test_cluster_configuration_uses_environment_and_metadata(self):
        source = next(source for kind, source in notebook_sources(ROOT / "serve_on_cluster.ipynb")
                      if kind == "code" and "def required_env" in source)
        metadata = {
            "spark.databricks.workspaceUrl": "workspace.example.com",
            "spark.databricks.clusterUsageTags.clusterOwnerOrgId": "example-org",
            "spark.databricks.clusterUsageTags.clusterId": "example-cluster",
        }
        environment = {
            "DATABRICKS_WAREHOUSE_ID": "example-warehouse",
            "DATABRICKS_SECRET_SCOPE": "example-scope",
            "DATABRICKS_TOKEN_SECRET_KEY": "example-key",
        }
        for missing in [None, *environment, "metadata"]:
            with self.subTest(missing=missing):
                settings = {key: value for key, value in environment.items() if key != missing}
                dbutils = MagicMock()
                namespace = {
                    "spark": SimpleNamespace(conf=SimpleNamespace(get=(metadata if missing != "metadata" else {}).get)),
                    "dbutils": dbutils,
                }
                output = io.StringIO()
                with patch.dict(os.environ, settings, clear=True), patch("os.getcwd", return_value=str(ROOT)), contextlib.redirect_stdout(output):
                    if missing:
                        with self.assertRaises(RuntimeError):
                            exec(compile(source, "<cluster-config>", "exec"), namespace)
                        dbutils.secrets.get.assert_not_called()
                    else:
                        exec(compile(source, "<cluster-config>", "exec"), namespace)
                        dbutils.secrets.get.assert_called_once_with("example-scope", "example-key")
                        self.assertEqual(namespace["WAREHOUSE_ID"], "example-warehouse")
                        self.assertEqual(namespace["PROXY_API"], "https://workspace.example.com/driver-proxy-api/o/example-org/example-cluster")
                        self.assertNotIn("example-cluster", output.getvalue())

    def test_cluster_cells_parse_without_redaction_bypass(self):
        for kind, source in notebook_sources(ROOT / "serve_on_cluster.ipynb"):
            if kind == "code" and not source.startswith("%"):
                ast.parse(source)
                self.assertNotIn("unredact", source)
                self.assertNotIn("d%61tabricks", source)


if __name__ == "__main__":
    unittest.main()