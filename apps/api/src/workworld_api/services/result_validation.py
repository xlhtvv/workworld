import copy
from collections import Counter
from typing import Any

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from sqlalchemy.orm import Session
from workworld_api.market_models import Agent
from workworld_api.models import Artifact, ScanStatus
from workworld_api.schema_catalog import get_schema
from workworld_api.task_models import Run, Task


class ResultValidationError(ValueError):
    pass


def _artifact_ids(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value} if value.startswith("artifact_") else set()
    if isinstance(value, list):
        return set().union(*(_artifact_ids(item) for item in value), set())
    if isinstance(value, dict):
        return set().union(*(_artifact_ids(item) for item in value.values()), set())
    return set()


def validate_result(db: Session, run: Run, payload: dict[str, Any]) -> None:
    task = db.get(Task, run.task_id)
    agent = db.get(Agent, run.agent_id)
    if task is None or agent is None:
        raise ResultValidationError("result_context_missing")
    schema = get_schema(task.schema_id, task.schema_version)
    output = payload.get("output")
    if schema is None or not isinstance(output, dict):
        raise ResultValidationError("result_output_missing")
    if list(Draft202012Validator(schema["output_schema"]).iter_errors(output)):
        raise ResultValidationError("result_output_schema_invalid")

    ids = _artifact_ids(output)
    artifacts: list[Artifact] = []
    for artifact_id in ids:
        artifact = db.get(Artifact, artifact_id)
        if (
            artifact is None
            or artifact.owner_id != agent.owner_id
            or artifact.task_id != task.id
            or artifact.direction != "output"
            or artifact.scan_status != ScanStatus.CLEAN
            or artifact.deleted_at is not None
        ):
            raise ResultValidationError("result_artifact_not_available")
        artifacts.append(artifact)
    counts = Counter(artifact.kind for artifact in artifacts)
    for requirement in schema["artifacts"]["output"]:
        count = counts[str(requirement["kind"])]
        if not int(requirement["min"]) <= count <= int(requirement["max"]):
            raise ResultValidationError("result_artifact_count_invalid")
    input_artifacts = list(
        db.query(Artifact).filter_by(task_id=task.id, direction="input", scan_status="clean")
    )
    for rule in schema["hard_validation"]:
        if rule in {"output_schema", "artifact_clean"}:
            continue
        if not _hard_rule(str(rule), task, output, artifacts, input_artifacts, schema):
            raise ResultValidationError(f"hard_validation_failed:{rule}")


def _hard_rule(
    rule: str,
    task: Task,
    output: dict[str, Any],
    artifacts: list[Artifact],
    input_artifacts: list[Artifact],
    schema: dict[str, Any],
) -> bool:
    if rule == "max_characters":
        limit = task.input_json.get("max_characters")
        if not isinstance(limit, int):
            limit = schema["input_schema"]["properties"]["max_characters"].get("default")
        text = output.get("text", output.get("summary"))
        return isinstance(text, str) and isinstance(limit, int) and len(text) <= limit
    if rule == "image_dimensions":
        return all(
            row.metadata_json.get("width") == task.input_json.get("width")
            and row.metadata_json.get("height") == task.input_json.get("height")
            for row in artifacts
            if row.kind == "image"
        )
    if rule == "image_decodable":
        output_images = [row for row in artifacts if row.kind == "image"]
        if not output_images or not all(
            isinstance(row.metadata_json.get("width"), int)
            and isinstance(row.metadata_json.get("height"), int)
            for row in output_images
        ):
            return False
        if task.input_json.get("preserve_dimensions", True):
            inputs = [row for row in input_artifacts if row.kind == "image"]
            return bool(inputs) and all(
                (row.metadata_json.get("width"), row.metadata_json.get("height"))
                == (inputs[0].metadata_json.get("width"), inputs[0].metadata_json.get("height"))
                for row in output_images
            )
        return True
    if rule == "target_language":
        return str(output.get("language", "")).casefold() == str(
            task.input_json.get("target_language", "")
        ).casefold()
    if rule == "answer_count":
        answers = output.get("answers")
        questions = task.input_json.get("questions")
        return isinstance(answers, list) and isinstance(questions, list) and len(answers) == len(
            questions
        )
    if rule == "timestamp_bounds":
        durations = [
            float(row.metadata_json["duration_seconds"])
            for row in input_artifacts
            if "duration_seconds" in row.metadata_json
        ]
        if not durations:
            return False
        duration = max(durations)
        if "segments" in output:
            return all(
                isinstance(item, dict)
                and 0 <= float(item.get("start", -1)) <= float(item.get("end", -1)) <= duration
                for item in output["segments"]
            )
        timestamps = output.get("timestamps", [])
        return isinstance(timestamps, list) and all(
            isinstance(value, (int, float)) and 0 <= value <= duration for value in timestamps
        )
    if rule == "archive_limits":
        return all(
            "file_count" in row.metadata_json
            and "uncompressed_size_bytes" in row.metadata_json
            and "nested_depth" in row.metadata_json
            for row in artifacts
            if row.kind == "archive"
        )
    if rule in {"paths_exist", "line_bounds"}:
        files = {
            str(item["path"]): item.get("line_count")
            for row in input_artifacts
            if row.kind == "repository_snapshot"
            for item in row.metadata_json.get("files", [])
            if isinstance(item, dict) and "path" in item
        }
        findings = output.get("findings", [])
        if rule == "paths_exist":
            return bool(files) and all(item.get("path") in files for item in findings)
        return all(
            item.get("line") is None
            or (
                isinstance(item.get("line"), int)
                and isinstance(files.get(str(item.get("path"))), int)
                and 1 <= item["line"] <= files[str(item["path"])]
            )
            for item in findings
        )
    if rule == "operation_postconditions":
        return bool(
            output.get("document")
            == _transform_json(
                task.input_json.get("document"), task.input_json.get("operations")
            )
        )
    return False


def _transform_json(document: Any, operations: Any) -> Any:
    if not isinstance(operations, list):
        return object()
    result = copy.deepcopy(document)
    if not isinstance(result, dict):
        return object()
    for operation in operations:
        if not isinstance(operation, dict):
            return object()
        path = [part for part in str(operation.get("path", "")).split(".") if part]
        if not path:
            return object()
        target = result
        for part in path[:-1]:
            child = target.get(part)
            if not isinstance(child, dict):
                if operation.get("op") != "set":
                    return object()
                child = {}
                target[part] = child
            target = child
        if operation.get("op") == "set":
            target[path[-1]] = operation.get("value")
        elif operation.get("op") == "remove" and path[-1] in target:
            del target[path[-1]]
        else:
            return object()
    return result
