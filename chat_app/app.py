"""Streamlit chat UI for the PFD Obligations MCP server.

The app calls a Databricks-hosted model and the configured MCP server to answer
questions. Both calls run as this app's service principal.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import streamlit as st
from databricks.sdk import WorkspaceClient

from agent import MCPToolBackend, ToolEvent, run_agent

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("pfd_chat")

MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "").strip()
MODEL = os.environ.get("SERVING_ENDPOINT", "databricks-claude-sonnet-5")
LOGO_PATH = Path(__file__).parent / "assets" / "rd-white-lockup-4x.png"

EXAMPLES = [
    # "What were total obligations by fiscal year?",
    # "Top 5 states by Single Family Housing dollars in FY2024",
    # "Compare grant vs. direct loan dollars for Water and Environmental programs in Iowa",
    # "Which program areas exist, and how much did each obligate overall?",
    "What was the total investment in Washington state in FY 2024?",
    "What portion of the investment in Washington state in FY 2024 was for water related projects?",
    "Which North Carolina county received the most RD investment in FY 2024?",
    "From FY 2021 through FY 2025, how much did RD invest in Illinois?",
    "Which kinds of businesses received the most RD investment for Rural Business in FY 2026?",
    "South Dakota had severe storms from June 28 - July 3, 2026. What portion of the South Dakota housing investment from RD (both direct and held by other lenders) was impacted?",
]

st.set_page_config(page_title="RDG Chat", layout="wide")
if not MCP_SERVER_URL:
    st.error("MCP_SERVER_URL is not configured. Set it in the app environment before starting chat.")
    st.stop()


def _escape_md(text: str) -> str:
    # Streamlit renders $...$ as LaTeX; escape dollar signs so amounts display as text.
    return text.replace("$", "\\$")


def _render_tool_events(events: list[dict]) -> None:
    if not events:
        return
    with st.expander(f"Data lookups ({len(events)})", expanded=False):
        for ev in events:
            st.markdown(f"**{ev['name']}**")
            st.code(json.dumps(ev["arguments"], indent=2), language="json")
            preview = ev["result"]
            st.code(preview[:2000] + ("\n..." if len(preview) > 2000 else ""), language="json")


if "history" not in st.session_state:
    st.session_state.history = []  # model-facing messages (user, assistant, tool)
    st.session_state.display = []  # what the UI shows: role, content, tool events

with st.sidebar:
    st.image(str(LOGO_PATH), width=200)
    st.caption("Ask questions about USDA Rural Development obligations, FY2017-FY2027.")

    user_email = st.context.headers.get("X-Forwarded-Email")
    if user_email:
        st.caption(f"Signed in as {user_email}")

    clicked = None
    with st.expander("Try asking", expanded=True):
        for ex in EXAMPLES:
            if st.button(ex, use_container_width=True):
                clicked = ex

    if st.button("Clear chat", type="secondary", use_container_width=True):
        st.session_state.history = []
        st.session_state.display = []
        st.rerun()

    with st.expander("How it works", expanded=False):
        st.markdown(f"**Model:** `{MODEL}`")
        st.markdown(
            """
            **Interface**  
            This chat is a Streamlit app hosted on Databricks Apps.

            **Answer process**  
            The model chooses from available data tools. The app runs each requested tool and
            returns its result to the model to write the answer. The model does not query the
            database directly.

            **MCP and data**  
            A Python FastMCP server exposes tools over the Model Context Protocol (MCP) using
            streamable HTTP. Obligation tools query
            `rd_edapt.analytics_bronze.pfd_obligations` through a Databricks SQL warehouse.
            Disaster lookups use FEMA's OpenFEMA API, and exposure tools combine
            FEMA-designated areas with obligation totals.

            **Data notes**  
            Source rows are aggregates, not individual transactions. Fiscal year 2027 is
            partial. Expand **Data lookups** below an answer to see the tools used, their
            arguments, and result previews.
            """
        )

st.title("Rural Data Gateway (RDG) Obligations Chat")

for item in st.session_state.display:
    with st.chat_message(item["role"]):
        st.markdown(_escape_md(item["content"]))
        _render_tool_events(item.get("tools", []))

prompt = st.chat_input("Ask about obligations, programs, states, years, major disaster impacts (from FEMA)...") or clicked

if prompt:
    st.session_state.history.append({"role": "user", "content": prompt})
    st.session_state.display.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(_escape_md(prompt))

    with st.chat_message("assistant"):
        events: list[dict] = []
        status = st.status("Looking up data...", expanded=False)

        def on_tool(ev: ToolEvent) -> None:
            events.append({"name": ev.name, "arguments": ev.arguments, "result": ev.result})
            status.write(f"Called {ev.name}")

        try:
            # Fresh clients per question so OAuth tokens are always current.
            w = WorkspaceClient()
            llm = w.serving_endpoints.get_open_ai_client()
            tools = MCPToolBackend(MCP_SERVER_URL, w)
            answer, new_messages = run_agent(llm, MODEL, tools, st.session_state.history, on_tool)
            status.update(label=f"Done ({len(events)} data lookups)", state="complete")
            st.session_state.history.extend(new_messages)
        except Exception as exc:
            log.exception("Chat request failed")
            status.update(label="Request failed", state="error")
            answer = (
                "Sorry, I couldn't reach the data service. The MCP server app may be stopped, "
                f"or this app may lack access to it.\n\nDetails: {exc}"
            )
            # Drop the unanswered question so the next request starts clean.
            st.session_state.history.pop()

        st.markdown(_escape_md(answer))
        _render_tool_events(events)
        st.session_state.display.append({"role": "assistant", "content": answer, "tools": events})
