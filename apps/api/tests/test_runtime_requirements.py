import tomllib
from pathlib import Path


def test_container_runtime_requirements_match_project_dependencies() -> None:
    root = Path(__file__).parents[3]
    project = tomllib.loads((root / "pyproject.toml").read_text())
    requirements = [
        line
        for line in (root / "requirements-runtime.txt").read_text().splitlines()
        if line and not line.startswith("#")
    ]

    assert requirements == project["project"]["dependencies"]


def test_worker_retention_path_does_not_import_artifact_scanning_runtime() -> None:
    root = Path(__file__).parents[3]
    retention = (
        root / "apps" / "api" / "src" / "workworld_api" / "services" / "artifact_retention.py"
    ).read_text()

    assert "services.artifact_errors import ArtifactError" in retention
    assert "services.artifacts import" not in retention


def test_worker_container_has_a_maintenance_heartbeat_healthcheck() -> None:
    root = Path(__file__).parents[3]
    compose = (root / "docker-compose.yml").read_text()
    worker = (root / "apps" / "worker" / "src" / "workworld_worker" / "__main__.py").read_text()

    assert "WORKWORLD_WORKER_HEALTH_PATH" in compose
    assert "healthcheck:" in compose.split("  worker:", 1)[1].split("  web:", 1)[0]
    assert "WORKWORLD_WORKER_HEALTH_PATH" in worker
