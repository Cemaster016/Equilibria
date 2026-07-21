"""
app.py
------
Single-page Streamlit demo for Equilibria. Run with:
    streamlit run src/equilibria/ui/app.py

Make sure the .env file has a real GOOGLE_API_KEY before running — every
agent in the pipeline needs it.
"""

from __future__ import annotations

import asyncio
import logging

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from equilibria.agents.orchestrator import run_equilibria, EquilibriaResult  # noqa: E402

EXAMPLE_PROMPT = (
    "We have funding for 5 new vaccination outreach points in Kano State. "
    "Prioritize reaching the most underserved children, weighted by distance "
    "from existing clinics and poor road access."
)

st.set_page_config(page_title="Equilibria", page_icon="🧭", layout="wide")


class StreamlitLogHandler(logging.Handler):
    """Streams the orchestrator's INFO-level log lines into a live st.status box."""

    def __init__(self, status_box):
        super().__init__()
        self.status_box = status_box
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))
        self.status_box.write(self.lines[-1])


def render_result(result: EquilibriaResult) -> None:
    if result.error:
        st.error(f"Something went wrong: {result.error}")
        return

    if result.needs_clarification:
        st.warning(f"I need a bit more information: {result.clarifying_question}")
        return

    map_tab, report_tab, validation_tab = st.tabs(["🗺️ Map", "📄 Report", "🛡️ Validation"])

    with map_tab:
        if result.map_html:
            st.components.v1.html(result.map_html, height=600, scrolling=True)
        else:
            st.info("No map was produced.")

    with report_tab:
        st.markdown(result.report_text or "_No report was produced._")

    with validation_tab:
        if result.validation_warnings:
            for warning in result.validation_warnings:
                st.warning(warning)
        else:
            st.success("No data-quality or bias concerns were flagged for this analysis.")


def main() -> None:
    st.title("🧭 Equilibria")
    st.caption("Optimizing for who's underserved, not who pays the most.")

    if "result" not in st.session_state:
        st.session_state.result = None

    user_request = st.text_area(
        "Describe what you need sited:",
        value=EXAMPLE_PROMPT,
        height=120,
    )

    if st.button("Run Equilibria", type="primary"):
        status_placeholder = st.status("Running the multi-agent pipeline...", expanded=True)
        handler = StreamlitLogHandler(status_placeholder)
        handler.setFormatter(logging.Formatter("%(message)s"))
        orchestrator_logger = logging.getLogger("equilibria.agents.orchestrator")
        orchestrator_logger.addHandler(handler)
        orchestrator_logger.setLevel(logging.INFO)

        try:
            result = asyncio.run(run_equilibria(user_request))
        finally:
            orchestrator_logger.removeHandler(handler)

        status_placeholder.update(label="Pipeline finished", state="complete")
        st.session_state.result = result

    if st.session_state.result is not None:
        render_result(st.session_state.result)


if __name__ == "__main__":
    main()
