from jsonschema import Draft202012Validator
from workworld_api.schema_catalog import get_schema, load_catalog

EXPECTED = {
    "text.generate@1.0",
    "text.summarize@1.0",
    "image.generate@1.0",
    "image.edit@1.0",
    "document.summarize@1.0",
    "document.translate@1.0",
    "spreadsheet.analyze@1.0",
    "audio.transcribe@1.0",
    "video.summarize@1.0",
    "archive.process@1.0",
    "repository.code-review@1.0",
    "json.transform@1.0",
}


def test_catalog_contains_exactly_the_twelve_mvp_contracts() -> None:
    definitions = load_catalog()["schemas"]
    actual = {f"{item['id']}@{item['version']}" for item in definitions}
    assert actual == EXPECTED


def test_every_contract_is_published_bilingual_and_valid_draft_2020_12() -> None:
    for definition in load_catalog()["schemas"]:
        assert definition["status"] == "published"
        assert set(definition["name"]) == {"en", "zh"}
        assert set(definition["description"]) == {"en", "zh"}
        Draft202012Validator.check_schema(definition["input_schema"])
        Draft202012Validator.check_schema(definition["output_schema"])
        assert set(definition["difficulty_multipliers"]) == {"simple", "standard", "complex"}
        assert definition["hard_validation"]
        assert definition["quality_rubric"]
        assert definition["metering"]["base_tokens"] >= 0


def test_schema_lookup_is_version_specific() -> None:
    assert get_schema("text.summarize", "1.0") is not None
    assert get_schema("text.summarize", "2.0") is None
