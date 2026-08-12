"""Zero-dependency PEP 517 wheel builder for the monorepo-only pure Python SDK."""

import base64
import csv
import hashlib
import io
import tarfile
import tomllib
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent
SOURCE = ROOT / "src" / "workworld_sdk"
DIST_NAME = "workworld_sdk"


def _project() -> dict[str, Any]:
    return dict(tomllib.loads((ROOT / "pyproject.toml").read_text())["project"])


def _version() -> str:
    return str(_project()["version"])


def _dist_info() -> str:
    return f"{DIST_NAME}-{_version()}.dist-info"


def _metadata() -> bytes:
    project = _project()
    dependencies = "".join(
        f"Requires-Dist: {dependency}\n" for dependency in project.get("dependencies", [])
    )
    return (
        "Metadata-Version: 2.3\n"
        f"Name: {project['name']}\n"
        f"Version: {project['version']}\n"
        f"Requires-Python: {project['requires-python']}\n"
        f"{dependencies}\n"
    ).encode()


def _wheel_metadata() -> bytes:
    return (
        b"Wheel-Version: 1.0\n"
        b"Generator: workworld-in-tree-builder 1\n"
        b"Root-Is-Purelib: true\n"
        b"Tag: py3-none-any\n"
    )


def _record_line(path: str, payload: bytes) -> tuple[str, str, str]:
    digest = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).rstrip(b"=").decode()
    return path, f"sha256={digest}", str(len(payload))


def get_requires_for_build_wheel(config_settings: dict[str, Any] | None = None) -> list[str]:
    del config_settings
    return []


def prepare_metadata_for_build_wheel(
    metadata_directory: str,
    config_settings: dict[str, Any] | None = None,
) -> str:
    del config_settings
    destination = Path(metadata_directory) / _dist_info()
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "METADATA").write_bytes(_metadata())
    (destination / "WHEEL").write_bytes(_wheel_metadata())
    (destination / "RECORD").write_text("")
    return destination.name


def build_wheel(
    wheel_directory: str,
    config_settings: dict[str, Any] | None = None,
    metadata_directory: str | None = None,
) -> str:
    del config_settings, metadata_directory
    filename = f"{DIST_NAME}-{_version()}-py3-none-any.whl"
    destination = Path(wheel_directory) / filename
    files = {
        f"workworld_sdk/{source.name}": source.read_bytes()
        for source in sorted(SOURCE.glob("*.py"))
    }
    files[f"{_dist_info()}/METADATA"] = _metadata()
    files[f"{_dist_info()}/WHEEL"] = _wheel_metadata()
    records = [_record_line(path, payload) for path, payload in files.items()]
    record_path = f"{_dist_info()}/RECORD"
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerows([*records, (record_path, "", "")])
    files[record_path] = output.getvalue().encode()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as wheel:
        for path, payload in files.items():
            wheel.writestr(path, payload)
    return filename


def get_requires_for_build_sdist(config_settings: dict[str, Any] | None = None) -> list[str]:
    del config_settings
    return []


def build_sdist(
    sdist_directory: str, config_settings: dict[str, Any] | None = None
) -> str:
    del config_settings
    base = f"workworld_sdk-{_version()}"
    filename = f"{base}.tar.gz"
    destination = Path(sdist_directory) / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(destination, "w:gz") as archive:
        for source in [ROOT / "pyproject.toml", ROOT / "_build_backend.py", *SOURCE.glob("*.py")]:
            archive.add(source, arcname=f"{base}/{source.relative_to(ROOT)}")
    return filename
