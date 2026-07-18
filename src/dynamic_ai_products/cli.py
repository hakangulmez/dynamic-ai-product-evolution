import typer
from .config import load_project_config

app = typer.Typer(add_completion=False)

@app.command()
def status() -> None:
    cfg = load_project_config()
    typer.echo(f"{cfg.project_name} schema={cfg.schema_version} full_run={cfg.full_run_enabled}")

if __name__ == "__main__":
    app()
