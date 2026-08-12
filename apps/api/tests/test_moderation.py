import io
import subprocess
import tempfile
import wave
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from workworld_api.config import Settings
from workworld_api.database import Base
from workworld_api.reputation_models import ModerationResult
from workworld_api.services.moderation import (
    ModerationBlocked,
    ModerationService,
    OpenAIAudioTranscriber,
    OpenAIModerationClassifier,
)


class SafeClassifier:
    def __init__(self) -> None:
        self.inputs: list[dict[str, object]] = []

    def classify(self, inputs: list[dict[str, object]]) -> tuple[list[str], str]:
        self.inputs = inputs
        return [], "a" * 64


class UnavailableClassifier:
    def classify(self, inputs: list[dict[str, object]]) -> tuple[list[str], str]:
        del inputs
        raise ModerationBlocked(["moderation_unavailable"])


class SafeTranscriber:
    def transcribe(self, payload: bytes, filename: str, mime_type: str) -> tuple[str, str]:
        assert payload and filename.endswith(".wav") and mime_type.startswith("audio/")
        return "safe spoken content", "b" * 64


def test_openai_moderation_document_and_real_image_preview() -> None:
    document = OpenAIModerationClassifier("key", "omni-moderation-latest").request_document(
        [{"type": "text", "text": "safe"}]
    )
    assert document == {
        "model": "omni-moderation-latest",
        "input": [{"type": "text", "text": "safe"}],
    }

    stream = io.BytesIO()
    Image.new("RGB", (1600, 1200), color=(1, 2, 3)).save(stream, format="PNG")
    classifier = SafeClassifier()
    engine = create_engine("sqlite+pysqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        result = ModerationService(
            db,
            Settings(
                moderation_mode="openai",
                openai_api_key="test-key",
            ),
            classifier,
        ).check_image("artifact", "artifact_1", stream.getvalue())
        assert result.mode == "openai"
        image_url = classifier.inputs[0]["image_url"]
        assert isinstance(image_url, dict)
        assert str(image_url["url"]).startswith("data:image/jpeg;base64,")


def test_openai_moderation_invalid_success_response_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, _limit: int) -> bytes:
            return b"not-json"

    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: Response())
    classifier = OpenAIModerationClassifier("key", "omni-moderation-latest")
    try:
        classifier.classify([{"type": "text", "text": "safe"}])
    except ModerationBlocked as exc:
        assert exc.categories == ["moderation_response_invalid"]
    else:
        raise AssertionError("invalid hosted response must fail closed")


def test_openai_moderation_failure_is_fail_closed_and_audited() -> None:
    engine = create_engine("sqlite+pysqlite://")
    Base.metadata.create_all(engine)
    settings = Settings(moderation_mode="openai", openai_api_key="test-key")
    with Session(engine) as db:
        try:
            ModerationService(db, settings, UnavailableClassifier()).check_text(
                "task", "task_1", "safe local text"
            )
        except ModerationBlocked as exc:
            assert exc.categories == ["moderation_unavailable"]
        else:
            raise AssertionError("hosted moderation failure must block")
        result = db.query(ModerationResult).one()
        assert result.blocked is True
        assert result.mode == "openai"
        assert result.categories_json == ["moderation_unavailable"]


def test_repeated_public_content_is_blocked_and_audited_as_spam() -> None:
    engine = create_engine("sqlite+pysqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        service = ModerationService(db, Settings())
        for index in range(5):
            service.check_text("agent_candidate", f"candidate_{index}", "Repeated safe name")
        try:
            service.check_text("agent_candidate", "candidate_6", "Repeated safe name")
        except ModerationBlocked as exc:
            assert exc.categories == ["spam_duplicate"]
        else:
            raise AssertionError("repeated public content must be blocked")
        blocked = db.query(ModerationResult).filter_by(subject_id="candidate_6").one()
        assert blocked.blocked is True
        assert blocked.categories_json == ["spam_duplicate"]


def test_audio_transcription_multipart_and_transcript_moderation() -> None:
    transcriber = OpenAIAudioTranscriber("key", "gpt-4o-mini-transcribe")
    body, content_type = transcriber.multipart_body(b"wav-bytes", "sample.wav", "audio/wav")
    assert content_type.startswith("multipart/form-data; boundary=")
    assert b'name="model"' in body and b"gpt-4o-mini-transcribe" in body
    assert b'name="file"; filename="sample.wav"' in body and b"wav-bytes" in body

    source = io.BytesIO()
    with wave.open(source, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8_000)
        audio.writeframes(b"\0\0" * 800)
    classifier = SafeClassifier()
    engine = create_engine("sqlite+pysqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        result = ModerationService(
            db,
            Settings(moderation_mode="openai", openai_api_key="test-key"),
            classifier,
            SafeTranscriber(),
        ).check_audio("artifact", "audio_1", source.getvalue(), "sample.wav", "audio/wav")
        assert result.mode == "openai_audio_transcript"
        assert classifier.inputs == [{"type": "text", "text": "safe spoken content"}]


def test_real_video_frames_are_extracted_for_hosted_moderation() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "sample.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=c=green:s=32x24:d=1:r=5",
                "-pix_fmt",
                "yuv420p",
                str(path),
            ],
            check=True,
            timeout=20,
        )
        payload = path.read_bytes()
    classifier = SafeClassifier()
    engine = create_engine("sqlite+pysqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        result = ModerationService(
            db,
            Settings(moderation_mode="openai", openai_api_key="test-key"),
            classifier,
            SafeTranscriber(),
        ).check_video("artifact", "video_1", payload, 1.0)
        assert result.mode == "openai_video_frames"
        assert len(classifier.inputs) >= 1
        assert all(item["type"] == "image_url" for item in classifier.inputs)


def test_video_extraction_timeout_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            subprocess.TimeoutExpired("ffmpeg", 30)
        ),
    )
    with pytest.raises(ModerationBlocked, match="video_frame_extraction_failed"):
        ModerationService._video_frames(b"video", 1.0)
