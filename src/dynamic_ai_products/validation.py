from __future__ import annotations
import json
from pathlib import Path
import typer
from jsonschema import Draft202012Validator

app = typer.Typer(add_completion=False)

@app.command()
def schemas(schema_dir: str = "schemas") -> None:
    root = Path(schema_dir)
    failures = []
    for path in sorted(root.glob("*.schema.json")):
        try:
            schema = json.loads(path.read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)
            typer.echo(f"OK {path}")
        except Exception as exc:  # pragma: no cover
            failures.append((path, exc))
            typer.echo(f"FAIL {path}: {exc}")
    if failures:
        raise typer.Exit(code=1)

if __name__ == "__main__":
    app()
