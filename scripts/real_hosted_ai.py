#!/usr/bin/env python3
"""Run paid, fail-closed acceptance against real OpenAI hosted models.

This script deliberately has no mock mode. It exercises a multimodal Responses
quality evaluation plus persisted text, image, audio, and video moderation audit
records. It prints hashes and model names only; API keys and raw responses are
never emitted.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import wave
from dataclasses import asdict
from typing import cast

from PIL import Image
from sqlalchemy import Table, create_engine, select
from sqlalchemy.orm import Session
from workworld_api.config import Settings
from workworld_api.reputation_models import ModerationResult
from workworld_api.services.evaluation import EvaluationError, OpenAIResponsesEvaluator
from workworld_api.services.moderation import ModerationBlocked, ModerationService


class HostedAcceptanceError(RuntimeError):
    pass


def require_api_key() -> str:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise HostedAcceptanceError(
            "OPENAI_API_KEY is required; real hosted acceptance never falls back to mocks"
        )
    return api_key


def image_fixture() -> bytes:
    stream = io.BytesIO()
    image = Image.new("RGB", (64, 64), color=(40, 100, 180))
    for coordinate in range(64):
        image.putpixel((coordinate, coordinate), (220, 40, 40))
    image.save(stream, format="PNG")
    return stream.getvalue()


def ffmpeg_fixture(arguments: list[str], label: str) -> bytes:
    try:
        result = subprocess.run(
            ["ffmpeg", "-v", "error", *arguments, "pipe:1"],
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HostedAcceptanceError(f"{label}_fixture_generation_failed") from exc
    if result.returncode != 0 or not result.stdout:
        raise HostedAcceptanceError(f"{label}_fixture_generation_failed")
    return result.stdout


def audio_fixture() -> bytes:
    pcm = ffmpeg_fixture(
        [
            "-f",
            "lavfi",
            "-i",
            "flite=text='This is a safe WorkWorld acceptance test.'",
            "-t",
            "3",
            "-ar",
            "16000",
            "-ac",
            "1",
            "-f",
            "s16le",
        ],
        "audio",
    )
    output = io.BytesIO()
    with wave.open(output, "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(16_000)
        target.writeframes(pcm)
    return output.getvalue()


def video_fixture() -> bytes:
    return ffmpeg_fixture(
        [
            "-f",
            "lavfi",
            "-i",
            "color=c=green:s=64x48:d=1:r=5",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "frag_keyframe+empty_moov",
            "-f",
            "mp4",
        ],
        "video",
    )


def verify_evaluation(settings: Settings, image: bytes) -> dict[str, object]:
    evaluator = OpenAIResponsesEvaluator(
        settings.openai_api_key,
        settings.openai_evaluation_model,
        timeout_seconds=120,
    )
    encoded = __import__("base64").b64encode(image).decode("ascii")
    result = evaluator.evaluate(
        {
            "task_input": {
                "instruction": "Evaluate whether the supplied image is technically readable.",
                "difficulty": "simple",
            },
            "task_output": {"description": "A blue square with a red diagonal."},
            "artifact_metadata": [{"width": 64, "height": 64, "mime_type": "image/png"}],
            "image_inputs": [
                {
                    "artifact_id": "hosted_acceptance_image",
                    "direction": "output",
                    "data_url": f"data:image/png;base64,{encoded}",
                }
            ],
        },
        ["technical readability", "agreement with the supplied description"],
    )
    if result.mode != "openai" or result.model != settings.openai_evaluation_model:
        raise HostedAcceptanceError("evaluation_did_not_use_configured_hosted_model")
    if not 0 <= result.quality_score <= 100 or not result.evidence:
        raise HostedAcceptanceError("evaluation_structured_output_invalid")
    if len(result.response_hash) != 64:
        raise HostedAcceptanceError("evaluation_response_hash_invalid")
    public = asdict(result)
    public.pop("evidence")
    public.pop("issues")
    return public


def verify_moderation(settings: Settings, image: bytes) -> list[dict[str, object]]:
    engine = create_engine("sqlite+pysqlite://")
    cast(Table, ModerationResult.__table__).create(engine)
    with Session(engine) as db:
        service = ModerationService(db, settings)
        checks = [
            service.check_text(
                "hosted_acceptance",
                "text",
                "A neutral description of a blue square with a red diagonal.",
            ),
            service.check_image("hosted_acceptance", "image", image),
            service.check_audio(
                "hosted_acceptance",
                "audio",
                audio_fixture(),
                "acceptance.wav",
                "audio/wav",
            ),
            service.check_video("hosted_acceptance", "video", video_fixture(), 1.0),
        ]
        db.commit()
        persisted = list(
            db.scalars(select(ModerationResult).order_by(ModerationResult.subject_id))
        )
        if len(persisted) != 4 or {row.id for row in persisted} != {row.id for row in checks}:
            raise HostedAcceptanceError("moderation_audit_records_not_persisted")
        expected_modes = {
            "text": "openai",
            "image": "openai",
            "audio": "openai_audio_transcript",
            "video": "openai_video_frames",
        }
        for row in persisted:
            if row.blocked or row.mode != expected_modes[row.subject_id]:
                raise HostedAcceptanceError(f"moderation_check_failed:{row.subject_id}")
            if len(row.input_hash) != 64 or len(row.response_hash) != 64:
                raise HostedAcceptanceError(f"moderation_hash_invalid:{row.subject_id}")
        return [
            {
                "subject": row.subject_id,
                "mode": row.mode,
                "model": row.model,
                "response_hash": row.response_hash,
            }
            for row in persisted
        ]


def main() -> int:
    try:
        api_key = require_api_key()
        settings = Settings(
            evaluation_mode="openai",
            moderation_mode="openai",
            openai_api_key=api_key,
            openai_evaluation_model=os.environ.get("OPENAI_EVALUATION_MODEL", "gpt-5-mini"),
            openai_moderation_model=os.environ.get(
                "OPENAI_MODERATION_MODEL", "omni-moderation-latest"
            ),
            openai_transcription_model=os.environ.get(
                "OPENAI_TRANSCRIPTION_MODEL", "gpt-4o-mini-transcribe"
            ),
        )
        image = image_fixture()
        evidence = {
            "evaluation": verify_evaluation(settings, image),
            "moderation": verify_moderation(settings, image),
        }
    except (HostedAcceptanceError, EvaluationError, ModerationBlocked) as exc:
        print(f"real_hosted_ai_failed:{exc}", file=sys.stderr)
        return 1
    print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
