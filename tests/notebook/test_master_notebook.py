from pathlib import Path

import nbformat


def test_master_notebook_is_valid_and_has_required_sections() -> None:
    root = Path(__file__).resolve().parents[2]
    path = root / "notebooks" / "00_MASTER_PIPELINE.ipynb"
    assert path.exists()
    notebook = nbformat.read(path, as_version=4)
    text = "\n".join(cell.source for cell in notebook.cells if cell.cell_type == "markdown")
    required = [
        "Master Pipeline Notebook",
        "Phase A",
        "Phase B",
        "Phase C",
        "Phase D",
        "Phase E",
        "Eval gates",
        "Stage execution controller",
        "Session-closing checklist",
    ]
    for heading in required:
        assert heading in text


def test_notebook_defaults_to_safe_status_mode() -> None:
    root = Path(__file__).resolve().parents[2]
    notebook = nbformat.read(root / "notebooks" / "00_MASTER_PIPELINE.ipynb", as_version=4)
    sources = "\n".join(cell.source for cell in notebook.cells if cell.cell_type == "code")
    assert 'EXECUTION_MODE = NOTEBOOK_CONFIG.get("execution_mode", "status")' in sources
    assert "ALLOW_STUB_EXECUTION" in sources
