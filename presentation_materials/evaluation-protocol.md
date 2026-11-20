# Rural Data Gateway MCP Evaluation

**Authors:** Bob Dinterman and Jess Chandler

## 1. Testing Methodology

We evaluated the Rural Data Obligations MCP server through the chat application's responses to six representative Rural Development investment questions. We manually compared the results with reference calculations written in [example_tests.ipynb](../example_tests.ipynb). The reference calculations query `rd_edapt.analytics_bronze.pfd_obligations` directly with PySpark and use OpenFEMA for disaster-designated areas. Together, these cases provide a limited cross-section of common investment questions, not an exhaustive test of every supported query.

The goal was to determine whether the MCP-assisted workflow could reproduce the results of our manually coded approach. We also wanted to ensure that a routine request would not generate excessive tool calls as the agent determined what to do. Our tests of conformance as completed through a manual functional evaluation, not an automated benchmark.

| Reference case | Basis for manual comparison |
| --- | --- |
| Washington investment, FY 2024 | Sum of obligation amounts for the state and fiscal year |
| Washington water-related share, FY 2024 | Water and Environmental obligations divided by all Washington obligations for the same year |
| Top North Carolina county, FY 2024 | Ranked county totals, distinguishing `Not Available` from a named county |
| Illinois investment, FY 2021-2025 | Annual totals and the combined total across the inclusive five-year period |
| Business sectors, FY 2026 | Ranked NAICS sector totals for the Commercial portfolio, distinguishing `Other or Not Defined` from a named sector |
| South Dakota housing loans in disaster-designated areas | FEMA disaster lookup and county FIPS matching; residential loan obligations in designated counties divided by the statewide total, with no fiscal-year restriction |

These comparisons check agreement with a separately coded calculation over the same source data. Using the same source table keeps the comparison focused on differences in filters, groupings, and calculations. They do not independently establish that the source data is complete or correct. The business-sector reference uses the Commercial portfolio, not a narrower Rural Business program filter.

We also maintain automated regression tests alongside the manual evaluation:

| Test area | Automated checks |
| --- | --- |
| MCP server ([tests/test_mcp_app.py](../tests/test_mcp_app.py)) | Expected registration of all 15 tools; exposure-tool required inputs and caveat text; health response; loopback binding; parameterized filters; paging and empty aggregation pages; FEMA lookup deduplication; county/statewide exposure calculations; result serialization; streamable HTTP startup |
| Date helpers ([tests/test_mcp_app.py](../tests/test_mcp_app.py)) | Frozen-clock checks of ISO dates, default UTC and explicit timezone behavior, September 30/October 1 fiscal-year rollover, calendar-year rollover, leap day, fiscal-year start/end dates, and invalid timezone errors |
| Local chat transport ([tests/test_local_chat.py](../tests/test_local_chat.py)) | Rejects non-loopback URLs, non-HTTP schemes, and embedded credentials; discovers and calls tools through a mocked MCP session without Databricks authentication headers on local requests |
| General catalog browser ([tests/test_config.py](../tests/test_config.py), [tests/test_databricks.py](../tests/test_databricks.py)) | Configuration validation, preview limits, identifier quoting, result serialization, and connection/cursor cleanup; these checks cover the separate general-purpose server |

The automated tests use mocks or fakes for Databricks, FEMA, and local MCP transport. They check implementation behavior, not live service availability or natural-language answer quality, which as describe above, was completed manually.

## 2. Performance Metrics

Our primary measure was **agreement with the notebook reference results**: dollar totals, calculated shares, and ranking results for the example questions. This checks functional correctness for the selected use cases, not model quality across arbitrary questions.

| Measure | Evaluation evidence |
| --- | --- |
| Coverage | Six reference scenarios covering totals, shares, rankings, multi-year aggregation, sectors, and cross-source geographic matching |
| Verification method | Manual comparison against notebook calculations |
| Automated regression coverage | Tool registration and selected server, transport, configuration, and query behaviors; test pass/fail results are separate from answer accuracy |
| Regression run, November 19, 2026 | All 21 test methods passed, including three added for date helpers. The checks include all 15 expected tool registrations, exposure input schema and caveat text, FEMA source URL attribution, and date/fiscal-year boundary behavior. |
| Numerical accuracy rate | We did not record output; no accuracy percentage is reported, but we did not observe failures |
| Repeated-run consistency | Because our evaluation was manual, this is not reported; we saw some difference in the wording of answers and inconsistent knowledge by the agent on what year it was, but we did not observe drift in the content |

The manual verification described here reflects the team's testing, not a reproducible results archive. We do not claim a benchmark score or a measured improvement over a no-tool baseline.

## 3. Security Considerations

We take security seriously. The server was designed to only be able to respond to a limited scope.

- **Public-facing data:** The MCP server only has acess to an already aggregated, publicly available dataset.
- **Read-only tools:** The MCP server exposes predefined queries rather than arbitrary SQL or data modification. Filter values are parameterized, selectable query columns are allow-listed, and search results are bounded.
- **Access control:** Hosted apps use Databricks app service principals. Permissions should be limited to the required warehouse, source table, model endpoint, and MCP app.
- **Local access:** The local MCP endpoint is unauthenticated. The provided startup scripts bind to `127.0.0.1`; keep it on loopback and do not expose it to a network.
- **Data handling:** Keep credentials out of source control and evaluation artifacts. Confirm permitted use and sharing before retaining prompts, returned records, or screenshots. Read-only access alone does not prevent inappropriate disclosure.
- **Untrusted input:** User questions, model-selected arguments, and OpenFEMA responses require validation. Prompt instructions alone are not a security boundary.
- **Responsible interpretation:** FEMA-area results describe historical loan obligations in designated areas, not current balances, unpaid principal, physical damage, or actual loss. They are not credit, eligibility, or emergency-response determinations.

Automated tests exercise selected safeguards, including SQL filter parameterization, local loopback restrictions, rejection of credentials embedded in local URLs, and general catalog-browser preview limits and identifier quoting. These are targeted regression checks, not a dedicated security assessment. Neither they nor the manual result comparisons establish comprehensive resistance to prompt injection, unauthorized access, or data leakage.

## 4. Lessons Learned through iterations and Applied

The notebook reference work highlighted four practical lessons:

- **Missing categories affect rankings.** `Not Available` counties and `Other or Not Defined` sectors can rank above named categories. We explicitly tell the agent to explain the missing category and distinguish the leading named result instead of silently excluding it.
- **Business terms need explicit filters.** The reference maps water-related investment to `Water and Environmental` and the business-sector example to the Commercial portfolio. We tell the agent to make those choices visible so users can judge whether they match the question.
- **Obligations are not outstanding balances.** The housing example supports a historical geographic exposure proxy, but the dataset cannot establish unpaid principal at risk or actual disaster damage.
- **Combining sources requires geographic care.** We force the agent to select the correct FEMA disaster and match padded state/county FIPS codes. Keep the numerator and denominator consistent in loan scope and time period.

## 5. Future Testing

There are many ways that the testing of this suite of tools could be improved. The current testing was what we had time for in this proof of concept.

We would have liked to set up an automated judge to run tests but we did not see how to use orchestration tools, like Langchain, within our environment. Some method for testing the MCP output would be required before going public with this tool.

More kinds of questions (more than the six we identified) would need to be tested to prove the tools were robust.

Keep regression tests aligned with tool schemas and helper return values, and rerun the suite after changes to the implementation.
