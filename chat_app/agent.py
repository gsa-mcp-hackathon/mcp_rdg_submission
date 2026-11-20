"""Tool-calling agent loop: a Databricks-hosted LLM that answers questions with MCP tools.

Kept free of Streamlit so it can be tested on its own (see `ToolBackend`).
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Callable, Protocol
from urllib.parse import urlsplit

log = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 8
MAX_TOOL_RESULT_CHARS = 20_000
MAX_USER_TURNS_IN_CONTEXT = 6

SYSTEM_PROMPT = """You are a data assistant for USDA Rural Development program obligations.
You answer questions using tools backed by the table rd_edapt.analytics_bronze.pfd_obligations
(about 579K rows, fiscal years 2017-2027).

About the data:
- Each row is an aggregate of obligations for a fiscal year, location (state, county, ZIP,
  congressional district), program (programarea, programlabel, fundingcode) and recipient.
- obl_amt is obligated dollars; obl_counts is the number of obligations. Totals are SUM(obl_amt)
  and SUM(obl_counts); never count rows as if they were obligations.
- investment_type is 'Grant Funds', 'Loan Funds - Direct' or 'Loan Funds - Guaranteed'.
- portfolio_group is 'Residential' or 'Commercial'. States use 2-letter abbreviations.
- Fiscal year 2027 is partial, and the most recent year may be incomplete.

How to work:
- Prefer summarize_obligations for totals, rankings and trends; use search_obligations only for
  row-level examples.
- If you are unsure of an exact filter value (program name, label, county), call
  list_distinct_values first instead of guessing.
- State which filters you applied. Format dollars readably (for example 1.2 billion dollars or
  4.5M) and say when results are limited or partial.
- If a tool returns an error, explain it plainly. Do not invent numbers.
"""


class ToolBackend(Protocol):
    """Source of tools for the agent: OpenAI-style tool specs plus a way to call them."""

    def list_tools(self) -> list[dict[str, Any]]: ...

    def call_tool(self, name: str, arguments: dict[str, Any]) -> str: ...


def to_openai_tool(name: str, description: str | None, schema: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description or "",
            "parameters": schema or {"type": "object", "properties": {}},
        },
    }


class LocalMCPClient:
    """Unauthenticated MCP transport restricted to loopback addresses."""

    def __init__(self, server_url: str) -> None:
        parsed = urlsplit(server_url)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("Local MCP connections require a loopback HTTP URL")
        self.server_url = server_url

    async def _request(self, name: str | None = None, arguments: dict[str, Any] | None = None) -> Any:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        async with streamablehttp_client(self.server_url) as (reader, writer, _):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                if name is None:
                    return (await session.list_tools()).tools
                return await session.call_tool(name, arguments or {})

    def list_tools(self) -> Any:
        return asyncio.run(self._request())

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        return asyncio.run(self._request(name, arguments))


class MCPToolBackend:
    """Tools from a local server or an authenticated Databricks App."""

    def __init__(self, server_url: str, workspace_client: Any) -> None:
        if urlsplit(server_url).hostname in {"localhost", "127.0.0.1", "::1"}:
            self._client = LocalMCPClient(server_url)
        else:
            from databricks_mcp import DatabricksMCPClient

            self._client = DatabricksMCPClient(server_url=server_url, workspace_client=workspace_client)
        self._tools: list[dict[str, Any]] | None = None

    def list_tools(self) -> list[dict[str, Any]]:
        if self._tools is None:
            self._tools = [
                to_openai_tool(t.name, t.description, t.inputSchema)
                for t in self._client.list_tools()
            ]
        return self._tools

    def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        result = self._client.call_tool(name, arguments)
        text = "\n".join(
            c.text for c in (result.content or []) if getattr(c, "text", None)
        )
        if getattr(result, "isError", False):
            return f"Tool error: {text}"
        return text


def content_text(content: Any) -> str:
    """Return message content as plain text.

    The endpoint usually returns a string, but can return a list of content blocks
    (e.g. [{"type": "text", "text": "..."}]); keep only the text blocks.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
                continue
            get = block.get if isinstance(block, dict) else (lambda k, d=None, b=block: getattr(b, k, d))
            if get("type", "text") in ("text", "output_text") and isinstance(get("text"), str):
                parts.append(get("text"))
        return "".join(parts)
    return str(content)


@dataclass
class ToolEvent:
    name: str
    arguments: dict[str, Any]
    result: str


def trim_history(history: list[dict[str, Any]], max_user_turns: int = MAX_USER_TURNS_IN_CONTEXT) -> list[dict[str, Any]]:
    """Keep the last N user turns, cutting only at user messages so tool calls stay paired."""
    user_idx = [i for i, m in enumerate(history) if m.get("role") == "user"]
    if len(user_idx) <= max_user_turns:
        return list(history)
    return list(history[user_idx[-max_user_turns]:])


def run_agent(
    llm: Any,
    model: str,
    tools: ToolBackend,
    history: list[dict[str, Any]],
    on_tool: Callable[[ToolEvent], None] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Run the tool-calling loop for the latest user message in `history`.

    Returns the final answer and the messages to append to history (assistant turns, tool
    calls and tool results).
    """
    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}, *trim_history(history)]
    new_messages: list[dict[str, Any]] = []
    specs = tools.list_tools()

    for _ in range(MAX_TOOL_ROUNDS):
        response = llm.chat.completions.create(
            model=model, messages=messages, tools=specs, max_tokens=2000
        )
        msg = response.choices[0].message
        if not msg.tool_calls:
            final = {"role": "assistant", "content": content_text(msg.content)}
            new_messages.append(final)
            return final["content"], new_messages

        assistant = {
            "role": "assistant",
            "content": content_text(msg.content) or None,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments or "{}"},
                }
                for tc in msg.tool_calls
            ],
        }
        messages.append(assistant)
        new_messages.append(assistant)

        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            try:
                result = tools.call_tool(tc.function.name, args)
            except Exception as exc:  # surface tool failures to the model instead of crashing
                log.exception("Tool %s failed", tc.function.name)
                result = f"Tool error: {exc}"
            if len(result) > MAX_TOOL_RESULT_CHARS:
                result = result[:MAX_TOOL_RESULT_CHARS] + "\n...[truncated]"
            if on_tool:
                on_tool(ToolEvent(tc.function.name, args, result))
            tool_msg = {"role": "tool", "tool_call_id": tc.id, "content": result}
            messages.append(tool_msg)
            new_messages.append(tool_msg)

    final_text = "I stopped after too many tool calls. Try asking a narrower question."
    new_messages.append({"role": "assistant", "content": final_text})
    return final_text, new_messages
