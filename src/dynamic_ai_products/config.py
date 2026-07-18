from pathlib import Path
from pydantic import BaseModel
import yaml

class ProjectConfig(BaseModel):
    project_name: str
    schema_version: str
    observation_window: dict
    source_policy: str
    full_run_enabled: bool = False


def load_project_config(path: str | Path = "configs/project.yaml") -> ProjectConfig:
    with Path(path).open("r", encoding="utf-8") as f:
        return ProjectConfig.model_validate(yaml.safe_load(f))
