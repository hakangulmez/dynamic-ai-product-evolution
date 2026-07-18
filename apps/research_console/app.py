"""Pre-harness local Research Console shell.

This app is intentionally read-only. It verifies that the local Streamlit setup works,
shows the canonical pipeline registry, and links the researcher to governing documents.
The full review console must not be implemented until the evaluation harness is ready.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import streamlit as st
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
STAGE_REGISTRY = REPO_ROOT / "configs" / "pipeline_stages.yaml"


def load_stage_registry() -> dict:
    """Load the canonical pipeline stage registry."""
    if not STAGE_REGISTRY.exists():
        return {"stages": [], "registry_version": "missing"}
    with STAGE_REGISTRY.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {"stages": []}


def count_files(pattern: str) -> int:
    """Count repository files matching a glob pattern."""
    return sum(1 for path in REPO_ROOT.glob(pattern) if path.is_file())


st.set_page_config(
    page_title="Dynamic AI Product Evolution — Research Console",
    page_icon="🧭",
    layout="wide",
)

registry = load_stage_registry()
stages = registry.get("stages", [])
status_counts = Counter(str(stage.get("status", "unknown")) for stage in stages)

st.title("Dynamic AI Product Evolution")
st.caption("Local research console — setup and read-only project status")

st.info(
    "This is the safe pre-harness console shell. It does not run paid models, mutate "
    "research data, or write review decisions. Full evaluation and adjudication pages "
    "remain gated behind Phase 1 of the evaluation harness."
)

col1, col2, col3, col4 = st.columns(4)
col1.metric("Pipeline stages", len(stages))
col2.metric("Specifications", count_files("specs/SPEC-*.md"))
col3.metric("Prompt files", count_files("prompts/**/*.md"))
col4.metric("Test files", count_files("tests/**/test_*.py"))

st.subheader("Implementation status")
status_rows = [
    {"status": status, "stage_count": count}
    for status, count in sorted(status_counts.items())
]
if status_rows:
    st.dataframe(status_rows, use_container_width=True, hide_index=True)
else:
    st.warning("No pipeline stages were found in the registry.")

st.subheader("Canonical workflow")
if stages:
    stage_rows = [
        {
            "id": str(stage.get("id", "")),
            "stage": stage.get("name", ""),
            "phase": stage.get("phase", ""),
            "status": stage.get("status", ""),
            "script": stage.get("script", ""),
            "spec": stage.get("spec", ""),
            "gate": stage.get("gate", ""),
        }
        for stage in stages
    ]
    st.dataframe(stage_rows, use_container_width=True, hide_index=True)

st.subheader("Start here")
st.markdown(
    """
- [`RESEARCH_HOME.md`](../../RESEARCH_HOME.md) — Obsidian-friendly project map
- [`notebooks/00_MASTER_PIPELINE.ipynb`](../../notebooks/00_MASTER_PIPELINE.ipynb) — end-to-end workflow
- [`docs/THESIS_METHODOLOGY_AND_DATA.md`](../../docs/THESIS_METHODOLOGY_AND_DATA.md) — thesis methodology
- [`evals/EVAL_HARNESS.md`](../../evals/EVAL_HARNESS.md) — evaluation design
- [`docs/implementation/OBSIDIAN_AND_STREAMLIT_SETUP.md`](../../docs/implementation/OBSIDIAN_AND_STREAMLIT_SETUP.md) — local setup
"""
)

st.subheader("What becomes available later")
st.markdown(
    """
After Phase 1 of the evaluation harness passes its tests, the full console can add:

1. Eval overview and hard-gate status
2. Source evidence / prediction / gold comparison
3. Prompt-run comparison and regression inspection
4. Append-only production review queue
5. Product–capability–task explorer
6. Longitudinal transition review
7. Measurement lab
"""
)

with st.expander("Local path and environment details"):
    st.code(str(REPO_ROOT))
    st.write("Pipeline registry:", str(STAGE_REGISTRY))
    st.write("Registry version:", registry.get("registry_version", "unknown"))
