import streamlit as st

from config import get_settings
from ado_client import AzureDevOpsClient
from log_analyzer import LogAnalyzer
from llm_analyzer import LLMAnalyzer
from agent import PipelineRCAAgent

st.set_page_config(
    page_title="Azure DevOps Pipeline RCA Agent",
    page_icon="🔎",
    layout="wide",
)

st.title("🔎 Azure DevOps Pipeline RCA AI Agent")
st.caption(
    "Reads failed builds, timeline records and logs, then produces "
    "evidence-based root-cause analysis."
)

@st.cache_resource
def create_agent():
    settings = get_settings()

    ado = AzureDevOpsClient(
        settings.ado_organization,
        settings.ado_project,
        settings.ado_pat,
    )

    llm = LLMAnalyzer(settings)

    analyzer = LogAnalyzer(
        context_lines=settings.context_lines,
        max_log_chars=settings.max_log_chars,
    )

    return PipelineRCAAgent(ado, llm, analyzer)

settings = get_settings()

with st.sidebar:
    st.header("Configuration")
    st.write("Organization:", settings.ado_organization or "Not configured")
    st.write("Project:", settings.ado_project or "Not configured")
    st.write("LLM:", settings.llm_provider)

    build_reference = st.text_input(
        "Build ID or number (blank = latest failed)",
        placeholder="e.g. 12345 or 20260930.1",
    )

if st.button("Analyze Build", type="primary"):
    try:
        with st.spinner("Reading build, timeline and logs..."):
            agent = create_agent()

            if build_reference.strip():
                build_reference = build_reference.strip()
                if build_reference.isdigit():
                    result = agent.analyze_build(int(build_reference))
                else:
                    result = agent.analyze_build_number(build_reference)
            else:
                result = agent.analyze_latest_failed()

        st.success("Analysis completed.")

        col1, col2, col3 = st.columns(3)
        col1.metric("Failure Category", result.failure_category)
        col2.metric("Confidence", result.confidence)
        col3.metric("Failed Task", result.failed_stage_or_task)

        st.subheader("Executive Summary")
        st.write(result.summary)

        st.subheader("Root Cause")
        st.info(result.root_cause)

        st.subheader("Evidence")
        for item in result.evidence:
            st.markdown(f"- {item}")

        st.subheader("Suggested Fixes")
        for item in result.suggested_fixes:
            st.markdown(f"- {item}")

        st.subheader("Verification Steps")
        for item in result.verification_steps:
            st.markdown(f"- {item}")

        st.subheader("Preventive Actions")
        for item in result.preventive_actions:
            st.markdown(f"- {item}")

        if result.uncertainty:
            st.subheader("Uncertainty / Missing Evidence")
            for item in result.uncertainty:
                st.warning(item)

        with st.expander("Structured JSON"):
            st.json(result.model_dump())

    except Exception as exc:
        st.error(str(exc))
        st.exception(exc)
