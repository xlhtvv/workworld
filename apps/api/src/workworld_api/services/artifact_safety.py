import hashlib
import json
import re
import subprocess
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from tempfile import SpooledTemporaryFile
from typing import IO, Any

import magic
from PIL import Image

CHUNK_SIZE = 1024 * 1024
MAX_ARCHIVE_FILES = 10_000
MAX_ARCHIVE_UNCOMPRESSED = 2 * 1024 * 1024 * 1024
MAX_ARCHIVE_RATIO = 200
MAX_ARCHIVE_DEPTH = 3


class UnsafeArtifact(ValueError):
    pass


@dataclass
class InspectedArtifact:
    sha256: str
    size_bytes: int
    mime_type: str
    metadata: dict[str, Any]
    file: IO[bytes]


def _extension_matches(name: str, mime_type: str) -> bool:
    suffix = Path(name).suffix.lower()
    accepted = {
        "image/png": {".png"},
        "image/jpeg": {".jpg", ".jpeg"},
        "image/webp": {".webp"},
        "application/json": {".json"},
        "application/pdf": {".pdf"},
        "application/zip": {".zip"},
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {".xlsx"},
        "audio/x-wav": {".wav"},
        "audio/wav": {".wav"},
        "text/plain": {".txt", ".md", ".csv"},
    }
    return mime_type not in accepted or suffix in accepted[mime_type]


def _refine_container_mime(file: IO[bytes], name: str, mime_type: str) -> str:
    if mime_type != "application/zip" or Path(name).suffix.lower() != ".xlsx":
        return mime_type
    file.seek(0)
    with zipfile.ZipFile(file) as archive:
        names = set(archive.namelist())
    if "[Content_Types].xml" in names and "xl/workbook.xml" in names:
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return mime_type


def _archive_metadata(file: IO[bytes]) -> dict[str, int]:
    file.seek(0)
    with zipfile.ZipFile(file) as archive:
        entries = archive.infolist()
        if len(entries) > MAX_ARCHIVE_FILES:
            raise UnsafeArtifact("archive_file_limit")
        total_compressed = sum(max(entry.compress_size, 1) for entry in entries)
        total_uncompressed = sum(entry.file_size for entry in entries)
        if total_uncompressed > MAX_ARCHIVE_UNCOMPRESSED:
            raise UnsafeArtifact("archive_uncompressed_limit")
        if total_uncompressed / max(total_compressed, 1) > MAX_ARCHIVE_RATIO:
            raise UnsafeArtifact("archive_ratio_limit")
        max_depth = 0
        for entry in entries:
            path = PurePosixPath(entry.filename)
            if path.is_absolute() or ".." in path.parts:
                raise UnsafeArtifact("archive_unsafe_path")
            max_depth = max(max_depth, len(path.parts) - 1)
            if max_depth > MAX_ARCHIVE_DEPTH:
                raise UnsafeArtifact("archive_depth_limit")
        return {
            "file_count": len(entries),
            "uncompressed_size_bytes": total_uncompressed,
            "nested_depth": max_depth,
        }


def _repository_metadata(file: IO[bytes]) -> dict[str, Any]:
    file.seek(0)
    with zipfile.ZipFile(file) as archive:
        try:
            manifest = json.loads(archive.read(".workworld-repository.json"))
        except (KeyError, json.JSONDecodeError) as exc:
            raise UnsafeArtifact("repository_manifest_required") from exc
        commit_sha = manifest.get("commit_sha")
        if not isinstance(commit_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", commit_sha):
            raise UnsafeArtifact("repository_commit_sha_invalid")
        code_suffixes = {".py", ".ts", ".tsx", ".js", ".go", ".rs", ".java", ".rb"}
        code_lines = 0
        language_counts: dict[str, int] = {}
        file_manifest: list[dict[str, Any]] = []
        files = [entry for entry in archive.infolist() if not entry.is_dir()]
        for entry in files:
            suffix = PurePosixPath(entry.filename).suffix.lower()
            line_count: int | None = None
            if suffix in code_suffixes and entry.file_size <= 5 * 1024 * 1024:
                lines = archive.read(entry).count(b"\n") + 1
                line_count = lines
                code_lines += lines
                language_counts[suffix.removeprefix(".")] = (
                    language_counts.get(suffix.removeprefix("."), 0) + lines
                )
            file_manifest.append({"path": entry.filename, "line_count": line_count})
        return {
            "commit_sha": commit_sha,
            "file_count": len(files),
            "code_line_count": code_lines,
            "language_line_counts": language_counts,
            "files": file_manifest,
        }


def _metadata(file: IO[bytes], mime_type: str, kind: str | None) -> dict[str, Any]:
    file.seek(0)
    if mime_type.startswith("image/"):
        with Image.open(file) as image:
            image.verify()
        file.seek(0)
        with Image.open(file) as image:
            return {
                "width": image.width,
                "height": image.height,
                "pixels": image.width * image.height,
                "format": image.format,
            }
    if mime_type == "application/json":
        document = json.load(file)

        def walk(value: Any, depth: int = 1) -> tuple[int, int]:
            if isinstance(value, dict):
                children = [walk(item, depth + 1) for item in value.values()]
            elif isinstance(value, list):
                children = [walk(item, depth + 1) for item in value]
            else:
                children = []
            return 1 + sum(item[0] for item in children), max(
                [depth, *(item[1] for item in children)]
            )

        nodes, depth = walk(document)
        return {"node_count": nodes, "max_depth": depth, "json_bytes": file.seek(0, 2)}
    if mime_type == "application/pdf":
        payload = file.read()
        page_count = len(re.findall(rb"/Type\s*/Page\b", payload))
        if page_count == 0:
            raise UnsafeArtifact("pdf_page_count_unavailable")
        return {"page_count": page_count, "measurement": "pdf_page_objects"}
    if mime_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
        archive_stats = _archive_metadata(file)
        file.seek(0)
        with zipfile.ZipFile(file) as workbook:
            sheets = [
                name
                for name in workbook.namelist()
                if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name)
            ]
            rows = 0
            cells = 0
            for sheet in sheets:
                content = workbook.read(sheet)
                rows += len(re.findall(rb"<row(?:\s|>)", content))
                cells += len(re.findall(rb"<c(?:\s|>)", content))
        return {
            **archive_stats,
            "worksheet_count": len(sheets),
            "used_row_count": rows,
            "nonempty_cell_upper_bound": cells,
        }
    if mime_type == "application/zip":
        if kind == "repository_snapshot":
            return {**_archive_metadata(file), **_repository_metadata(file)}
        return _archive_metadata(file)
    if mime_type.startswith("audio/") or mime_type.startswith("video/"):
        descriptor = file.fileno()
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration:stream=codec_type,width,height,r_frame_rate,sample_rate,channels",
                "-of",
                "json",
                f"/proc/self/fd/{descriptor}",
            ],
            check=False,
            capture_output=True,
            pass_fds=(descriptor,),
            timeout=15,
        )
        if result.returncode != 0:
            raise UnsafeArtifact("media_probe_failed")
        probe = json.loads(result.stdout)
        metadata: dict[str, Any] = {
            "duration_seconds": float(probe.get("format", {}).get("duration", 0))
        }
        for stream in probe.get("streams", []):
            if stream.get("codec_type") == "video":
                metadata.update(
                    width=stream.get("width"),
                    height=stream.get("height"),
                    frame_rate=stream.get("r_frame_rate"),
                )
            if stream.get("codec_type") == "audio":
                metadata.update(
                    sample_rate=stream.get("sample_rate"), channels=stream.get("channels")
                )
        return metadata
    if mime_type.startswith("text/"):
        text = file.read().decode("utf-8")
        tokens = re.findall(r"[\w]+|[^\s\w]", text, flags=re.UNICODE)
        cjk = len(re.findall(r"[\u3400-\u9fff]", text))
        return {
            "character_count": len(text),
            "line_count": len(text.splitlines()),
            "paragraph_count": len([part for part in re.split(r"\n\s*\n", text) if part]),
            "token_count": len(tokens),
            "tokenizer_version": "workworld_simple_v1",
            "language": "zh" if cjk > len(text) * 0.1 else "und",
        }
    return {}


def inspect_stream(
    chunks: Iterable[bytes], original_name: str, max_bytes: int, kind: str | None = None
) -> InspectedArtifact:
    digest = hashlib.sha256()
    size = 0
    file = SpooledTemporaryFile(max_size=16 * 1024 * 1024, mode="w+b")  # noqa: SIM115
    for chunk in chunks:
        size += len(chunk)
        if size > max_bytes:
            file.close()
            raise UnsafeArtifact("artifact_size_limit")
        digest.update(chunk)
        file.write(chunk)
    file.seek(0)
    sample = file.read(min(size, 256 * 1024))
    mime_type = magic.from_buffer(sample, mime=True)
    mime_type = _refine_container_mime(file, original_name, mime_type)
    if not _extension_matches(original_name, mime_type):
        file.close()
        raise UnsafeArtifact("mime_extension_mismatch")
    metadata = _metadata(file, mime_type, kind)
    metadata["bytes"] = size
    file.seek(0)
    return InspectedArtifact(digest.hexdigest(), size, mime_type, metadata, file)
