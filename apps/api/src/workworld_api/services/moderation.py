import base64
import hashlib
import io
import json
import re
import subprocess
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from workworld_api.config import Settings, get_settings
from workworld_api.reputation_models import ModerationResult
from workworld_api.services.endpoint_security import canonical_json

CONTACT_PATTERNS = {
    "contact_email": re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b"),
    "contact_phone": re.compile(r"(?<!\d)(?:\+?\d[\d\s()-]{7,}\d)(?!\d)"),
    "external_payment": re.compile(
        r"\b(?:paypal|venmo|cashapp|wire transfer|crypto wallet|支付宝|微信转账)\b",
        re.IGNORECASE,
    ),
}
PROHIBITED_PATTERNS = {
    "malware": re.compile(r"\b(?:ransomware|credential stealer|deploy malware)\b", re.IGNORECASE),
    "adult": re.compile(r"\b(?:explicit sexual content|child sexual)\b", re.IGNORECASE),
    "fraud": re.compile(r"\b(?:phishing kit|steal credit card|骗取银行卡)\b", re.IGNORECASE),
}
DUPLICATE_GUARDED_SUBJECTS = {
    "agent_candidate",
    "offering_candidate",
    "task",
    "application",
    "provider_profile",
    "review",
    "review_reply",
}
DUPLICATE_LIMIT = 5


class ModerationBlocked(ValueError):
    def __init__(self, categories: list[str]) -> None:
        super().__init__(f"content_blocked:{','.join(categories)}")
        self.categories = categories


class ModerationClassifier(Protocol):
    def classify(self, inputs: list[dict[str, Any]]) -> tuple[list[str], str]: ...


class AudioTranscriber(Protocol):
    def transcribe(self, payload: bytes, filename: str, mime_type: str) -> tuple[str, str]: ...


class OpenAIModerationClassifier:
    def __init__(self, api_key: str, model: str, timeout_seconds: int = 60) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    def request_document(self, inputs: list[dict[str, Any]]) -> dict[str, Any]:
        return {"model": self.model, "input": inputs}

    def classify(self, inputs: list[dict[str, Any]]) -> tuple[list[str], str]:
        body = canonical_json(self.request_document(inputs))
        request = urllib.request.Request(
            "https://api.openai.com/v1/moderations",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read(2_000_001)
        except (OSError, urllib.error.HTTPError) as exc:
            raise ModerationBlocked(["moderation_unavailable"]) from exc
        if len(raw) > 2_000_000:
            raise ModerationBlocked(["moderation_response_too_large"])
        try:
            document = json.loads(raw)
            result = document["results"][0]
            categories = [
                str(category)
                for category, matched in dict(result["categories"]).items()
                if matched
            ]
        except (IndexError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ModerationBlocked(["moderation_response_invalid"]) from exc
        return categories, hashlib.sha256(raw).hexdigest()


class OpenAIAudioTranscriber:
    def __init__(self, api_key: str, model: str, timeout_seconds: int = 120) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    def multipart_body(
        self, payload: bytes, filename: str, mime_type: str
    ) -> tuple[bytes, str]:
        boundary = f"workworld-{uuid.uuid4().hex}"
        chunks = [
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"model\"\r\n\r\n"
            f"{self.model}\r\n".encode(),
            f"--{boundary}\r\nContent-Disposition: form-data; "
            "name=\"response_format\"\r\n\r\njson\r\n".encode(),
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
            f"filename=\"{filename.replace(chr(34), '')}\"\r\n"
            f"Content-Type: {mime_type}\r\n\r\n".encode(),
            payload,
            f"\r\n--{boundary}--\r\n".encode(),
        ]
        return b"".join(chunks), f"multipart/form-data; boundary={boundary}"

    def transcribe(self, payload: bytes, filename: str, mime_type: str) -> tuple[str, str]:
        body, content_type = self.multipart_body(payload, filename, mime_type)
        request = urllib.request.Request(
            "https://api.openai.com/v1/audio/transcriptions",
            data=body,
            method="POST",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": content_type},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read(2_000_001)
        except (OSError, urllib.error.HTTPError) as exc:
            raise ModerationBlocked(["audio_transcription_unavailable"]) from exc
        if len(raw) > 2_000_000:
            raise ModerationBlocked(["audio_transcription_response_too_large"])
        try:
            text = str(json.loads(raw)["text"])
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ModerationBlocked(["audio_transcription_response_invalid"]) from exc
        return text, hashlib.sha256(raw).hexdigest()


class ModerationService:
    def __init__(
        self,
        db: Session,
        settings: Settings | None = None,
        classifier: ModerationClassifier | None = None,
        transcriber: AudioTranscriber | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.classifier = classifier or (
            OpenAIModerationClassifier(
                self.settings.openai_api_key, self.settings.openai_moderation_model
            )
            if self.settings.moderation_mode == "openai"
            else None
        )
        self.transcriber = transcriber or (
            OpenAIAudioTranscriber(
                self.settings.openai_api_key, self.settings.openai_transcription_model
            )
            if self.settings.moderation_mode == "openai"
            else None
        )

    def check_text(self, subject_type: str, subject_id: str, text: str) -> ModerationResult:
        categories = [
            category
            for category, pattern in {**CONTACT_PATTERNS, **PROHIBITED_PATTERNS}.items()
            if pattern.search(text)
        ]
        response_hash: str | None = None
        mode = "local_rules"
        model = "workworld_text_rules_v1"
        input_hash = hashlib.sha256(text.encode()).hexdigest()
        if not categories and subject_type in DUPLICATE_GUARDED_SUBJECTS:
            recent_duplicates = self.db.scalar(
                select(func.count(ModerationResult.id)).where(
                    ModerationResult.subject_type == subject_type,
                    ModerationResult.input_hash == input_hash,
                    ModerationResult.created_at >= datetime.now(UTC) - timedelta(hours=24),
                )
            )
            if (recent_duplicates or 0) >= DUPLICATE_LIMIT:
                categories.append("spam_duplicate")
        if not categories and self.classifier is not None:
            mode = "openai"
            model = self.settings.openai_moderation_model
            try:
                categories, response_hash = self.classifier.classify(
                    [{"type": "text", "text": text}]
                )
            except ModerationBlocked as exc:
                categories = exc.categories
        return self._record(
            subject_type, subject_id, text.encode(), categories, mode, model, response_hash
        )

    def check_image(
        self, subject_type: str, subject_id: str, payload: bytes
    ) -> ModerationResult:
        if self.classifier is None:
            return self._record(
                subject_type,
                subject_id,
                payload,
                [],
                "local_structure_only",
                "pillow_decode_v1",
                None,
            )
        data_url = self._image_data_url(payload)
        try:
            categories, response_hash = self.classifier.classify(
                [{"type": "image_url", "image_url": {"url": data_url}}]
            )
        except ModerationBlocked as exc:
            categories = exc.categories
            response_hash = None
        return self._record(
            subject_type,
            subject_id,
            payload,
            categories,
            "openai",
            self.settings.openai_moderation_model,
            response_hash,
        )

    def check_audio(
        self,
        subject_type: str,
        subject_id: str,
        payload: bytes,
        filename: str,
        mime_type: str,
    ) -> ModerationResult:
        if self.classifier is None or self.transcriber is None:
            return self._record(
                subject_type,
                subject_id,
                payload,
                [],
                "local_structure_only",
                "ffprobe_metadata_v1",
                None,
            )
        if len(payload) > self.settings.moderation_media_max_bytes:
            return self._record(
                subject_type,
                subject_id,
                payload,
                ["audio_moderation_size_limit"],
                "openai",
                self.settings.openai_moderation_model,
                None,
            )
        try:
            transcript, transcript_hash = self.transcriber.transcribe(
                payload, filename, mime_type
            )
            categories, moderation_hash = self.classifier.classify(
                [{"type": "text", "text": transcript}]
            )
            response_hash = hashlib.sha256(
                f"{transcript_hash}:{moderation_hash}".encode()
            ).hexdigest()
        except ModerationBlocked as exc:
            categories = exc.categories
            response_hash = None
        return self._record(
            subject_type,
            subject_id,
            payload,
            categories,
            "openai_audio_transcript",
            f"{self.settings.openai_transcription_model}+{self.settings.openai_moderation_model}",
            response_hash,
        )

    def check_video(
        self,
        subject_type: str,
        subject_id: str,
        payload: bytes,
        duration_seconds: float,
    ) -> ModerationResult:
        if self.classifier is None:
            return self._record(
                subject_type,
                subject_id,
                payload,
                [],
                "local_structure_only",
                "ffprobe_metadata_v1",
                None,
            )
        if len(payload) > self.settings.moderation_media_max_bytes:
            return self._record(
                subject_type,
                subject_id,
                payload,
                ["video_moderation_size_limit"],
                "openai",
                self.settings.openai_moderation_model,
                None,
            )
        try:
            frames = self._video_frames(payload, duration_seconds)
            inputs = [
                {"type": "image_url", "image_url": {"url": self._image_data_url(frame)}}
                for frame in frames
            ]
            categories, response_hash = self.classifier.classify(inputs)
        except ModerationBlocked as exc:
            categories = exc.categories
            response_hash = None
        return self._record(
            subject_type,
            subject_id,
            payload,
            categories,
            "openai_video_frames",
            self.settings.openai_moderation_model,
            response_hash,
        )

    @staticmethod
    def _image_data_url(payload: bytes) -> str:
        try:
            with Image.open(io.BytesIO(payload)) as source:
                source.seek(0)
                image = source.convert("RGB")
                image.thumbnail((1024, 1024))
                preview = io.BytesIO()
                image.save(preview, format="JPEG", quality=85, optimize=True)
        except (OSError, ValueError) as exc:
            raise ModerationBlocked(["image_moderation_decode_failed"]) from exc
        return f"data:image/jpeg;base64,{base64.b64encode(preview.getvalue()).decode()}"

    @staticmethod
    def _video_frames(payload: bytes, duration_seconds: float) -> list[bytes]:
        timestamps = sorted(
            {
                0.0,
                max(0.0, duration_seconds * 0.5),
                max(0.0, duration_seconds * 0.9),
            }
        )
        frames: list[bytes] = []
        for timestamp in timestamps:
            try:
                result = subprocess.run(
                    [
                        "ffmpeg",
                        "-v",
                        "error",
                        "-i",
                        "pipe:0",
                        "-ss",
                        f"{timestamp:.3f}",
                        "-frames:v",
                        "1",
                        "-f",
                        "image2pipe",
                        "-vcodec",
                        "png",
                        "pipe:1",
                    ],
                    input=payload,
                    capture_output=True,
                    timeout=30,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                continue
            if result.returncode == 0 and result.stdout:
                frames.append(result.stdout)
        if not frames:
            raise ModerationBlocked(["video_frame_extraction_failed"])
        return frames

    def _record(
        self,
        subject_type: str,
        subject_id: str,
        payload: bytes,
        categories: list[str],
        mode: str,
        model: str,
        response_hash: str | None,
    ) -> ModerationResult:
        result_payload = {"blocked": bool(categories), "categories": categories}
        result = ModerationResult(
            id=f"moderation_{uuid.uuid4().hex}",
            subject_type=subject_type,
            subject_id=subject_id,
            mode=mode,
            model=model,
            categories_json=categories,
            blocked=bool(categories),
            input_hash=hashlib.sha256(payload).hexdigest(),
            response_hash=response_hash
            or hashlib.sha256(canonical_json(result_payload)).hexdigest(),
            created_at=datetime.now(UTC),
        )
        self.db.add(result)
        self.db.flush()
        if categories:
            self.db.commit()
            raise ModerationBlocked(categories)
        return result
