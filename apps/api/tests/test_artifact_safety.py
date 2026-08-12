import io
import subprocess
import tempfile
import wave
import zipfile
from pathlib import Path

import pytest
from PIL import Image
from workworld_api.services.artifact_safety import UnsafeArtifact, inspect_stream
from workworld_api.services.clamav import ClamAVError, parse_response


def test_real_png_is_sniffed_hashed_and_measured() -> None:
    source = io.BytesIO()
    Image.new("RGB", (13, 7), color=(12, 34, 56)).save(source, format="PNG")
    payload = source.getvalue()
    inspected = inspect_stream([payload[:20], payload[20:]], "sample.png", 1024 * 1024)
    assert inspected.mime_type == "image/png"
    assert inspected.size_bytes == len(payload)
    assert inspected.metadata["width"] == 13
    assert inspected.metadata["height"] == 7


def test_mime_extension_mismatch_is_rejected() -> None:
    with pytest.raises(UnsafeArtifact, match="mime_extension_mismatch"):
        inspect_stream([b'{"safe": true}'], "payload.png", 1024)


def test_archive_path_traversal_is_rejected() -> None:
    source = io.BytesIO()
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("../escape.txt", "no")
    with pytest.raises(UnsafeArtifact, match="archive_unsafe_path"):
        inspect_stream([source.getvalue()], "unsafe.zip", 1024 * 1024)


def test_xlsx_structure_is_measured_without_extracting_files() -> None:
    source = io.BytesIO()
    with zipfile.ZipFile(source, "w") as workbook:
        workbook.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        )
        workbook.writestr("xl/workbook.xml", "<workbook/>")
        workbook.writestr(
            "xl/worksheets/sheet1.xml",
            '<worksheet><sheetData><row r="1"><c r="A1"><v>7</v></c></row></sheetData></worksheet>',
        )
    inspected = inspect_stream([source.getvalue()], "data.xlsx", 1024 * 1024)
    assert inspected.metadata["worksheet_count"] == 1
    assert inspected.metadata["used_row_count"] == 1
    assert inspected.metadata["nonempty_cell_upper_bound"] == 1


def test_clamav_wire_responses_are_fail_closed() -> None:
    assert parse_response(b"stream: OK\0").clean is True
    infected = parse_response(b"stream: Eicar-Signature FOUND\0")
    assert infected.clean is False
    assert infected.signature == "Eicar-Signature"
    with pytest.raises(ClamAVError):
        parse_response(b"stream: scanner unavailable ERROR\0")


def test_repository_snapshot_requires_commit_manifest_and_measures_code() -> None:
    source = io.BytesIO()
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr(
            ".workworld-repository.json",
            '{"commit_sha":"0123456789abcdef0123456789abcdef01234567"}',
        )
        archive.writestr("src/app.py", "print('one')\nprint('two')\n")
    inspected = inspect_stream(
        [source.getvalue()], "repository.zip", 1024 * 1024, "repository_snapshot"
    )
    assert inspected.metadata["commit_sha"] == "0123456789abcdef0123456789abcdef01234567"
    assert inspected.metadata["file_count"] == 2
    assert inspected.metadata["language_line_counts"]["py"] == 3
    assert inspected.metadata["files"] == [
        {"path": ".workworld-repository.json", "line_count": None},
        {"path": "src/app.py", "line_count": 3},
    ]


def test_real_wav_is_probed_for_duration_sample_rate_and_channels() -> None:
    source = io.BytesIO()
    with wave.open(source, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8_000)
        audio.writeframes(b"\0\0" * 800)
    inspected = inspect_stream([source.getvalue()], "speech.wav", 1024 * 1024, "audio")
    assert 0.09 <= inspected.metadata["duration_seconds"] <= 0.11
    assert inspected.metadata["sample_rate"] == "8000"
    assert inspected.metadata["channels"] == 1


def test_real_mp4_is_probed_for_duration_dimensions_and_frame_rate() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "fixture.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=c=blue:s=32x24:d=0.4:r=5",
                "-pix_fmt",
                "yuv420p",
                str(path),
            ],
            check=True,
            timeout=20,
        )
        payload = path.read_bytes()
    inspected = inspect_stream([payload], "fixture.mp4", 4 * 1024 * 1024, "video")
    assert inspected.metadata["width"] == 32
    assert inspected.metadata["height"] == 24
    assert inspected.metadata["frame_rate"] == "5/1"
    assert 0.3 <= inspected.metadata["duration_seconds"] <= 0.5
