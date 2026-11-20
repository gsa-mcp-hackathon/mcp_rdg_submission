import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "chat_app"))
try:
    from agent import LocalMCPClient, MCPToolBackend
finally:
    sys.path.pop(0)


class LocalChatTests(unittest.TestCase):
    def test_loopback_only(self):
        for address in ["http://127.0.0.1:8000/mcp", "http://localhost:8000/mcp", "http://[::1]:8000/mcp"]:
            self.assertEqual(LocalMCPClient(address).server_url, address)
        for address in ["http://example.com/mcp", "file://localhost/mcp", "http://user:secret@localhost/mcp"]:
            with self.assertRaises(ValueError):
                LocalMCPClient(address)

    def test_local_transport_has_no_databricks_auth(self):
        session = AsyncMock()
        session.list_tools.return_value = SimpleNamespace(tools=[
            SimpleNamespace(name="example", description="Example", inputSchema={"type": "object"}),
        ])
        session.call_tool.return_value = SimpleNamespace(
            content=[SimpleNamespace(text="result")], isError=False,
        )
        session_context = MagicMock()
        session_context.__aenter__ = AsyncMock(return_value=session)
        transport_context = MagicMock()
        transport_context.__aenter__ = AsyncMock(return_value=("reader", "writer", None))
        with (
            patch("mcp.ClientSession", return_value=session_context),
            patch("mcp.client.streamable_http.streamablehttp_client", return_value=transport_context) as transport,
        ):
            backend = MCPToolBackend("http://127.0.0.1:8000/mcp", object())
            self.assertEqual(backend.list_tools()[0]["function"]["name"], "example")
            backend.list_tools()
            self.assertEqual(backend.call_tool("example", {"state": "SD"}), "result")
        self.assertEqual(transport.call_count, 2)
        for call in transport.call_args_list:
            self.assertEqual(call.args, ("http://127.0.0.1:8000/mcp",))
            self.assertEqual(call.kwargs, {})
        session.call_tool.assert_awaited_once_with("example", {"state": "SD"})


if __name__ == "__main__":
    unittest.main()