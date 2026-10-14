"""离线单元测试：不调用模型、不需要 API Key，默认随 pytest 直接运行。"""

import json
from pathlib import Path

import pytest

from tests.cases import CASES, _load_cases
from translator import translate
from translator.models import TranslateResult, normalize_language
from translator.multi import build_translate_prompt, target_language
from translator.validators import MAX_TEXT_LENGTH, validate_text


class TestValidateText:
    @pytest.mark.parametrize("bad_input", [None, 123, ["hello"], {"text": "hi"}])
    def test_non_string_raises_type_error(self, bad_input) -> None:
        with pytest.raises(TypeError, match="输入必须为字符串"):
            validate_text(bad_input)  # type: ignore[arg-type]

    @pytest.mark.parametrize("empty_input", ["", " ", "   ", "\n\t\r"])
    def test_empty_or_whitespace_raises_value_error(self, empty_input: str) -> None:
        with pytest.raises(ValueError, match="输入不能为空"):
            validate_text(empty_input)

    def test_exceeding_max_length_raises_value_error(self) -> None:
        too_long = "a" * (MAX_TEXT_LENGTH + 1)
        with pytest.raises(ValueError, match="输入超长"):
            validate_text(too_long)

    def test_exact_max_length_passes(self) -> None:
        exact = "a" * MAX_TEXT_LENGTH
        assert validate_text(exact) == exact

    def test_preserves_original_text_verbatim(self) -> None:
        raw = "  Hello, world! \n"
        assert validate_text(raw) == raw


class TestLanguageRouting:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("zh", "zh"),
            ("  ZH  ", "zh"),
            ("zh-CN", "zh"),
            ("zh-TW", "zh"),
            ("zh_CN", "zh"),
            ("zh_Hant", "zh"),
            ("en-US", "en"),
            ("en_GB", "en"),
            ("JA", "ja"),
        ],
    )
    def test_normalize_language(self, raw: str, expected: str) -> None:
        assert normalize_language(raw) == expected

    @pytest.mark.parametrize("lang", ["zh", "ZH", "zh-CN", "zh-TW", "zh_CN", "zh_Hans"])
    def test_target_language_chinese_to_english(self, lang: str) -> None:
        assert target_language(lang) == "English"

    @pytest.mark.parametrize("lang", ["en", "ja", "fr", "ko", "und", "en-US"])
    def test_target_language_others_to_chinese(self, lang: str) -> None:
        assert target_language(lang) == "Chinese"

    def test_build_translate_prompt(self) -> None:
        prompt = build_translate_prompt("こんにちは", "Chinese")
        assert "Chinese" in prompt
        assert "こんにちは" in prompt


class TestTranslateEntrypoint:
    def test_unknown_mode_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="unknown mode"):
            translate("Hello", mode="invalid")

    def test_invalid_text_rejected_before_model_call(self) -> None:
        with pytest.raises(ValueError, match="输入不能为空"):
            translate("   ", mode="single")

    def test_translate_result_contract(self) -> None:
        res = TranslateResult(query_input="你好", language="zh", result="Hello")
        assert res.model_dump() == {
            "query_input": "你好",
            "language": "zh",
            "result": "Hello",
        }


class TestCasesLoader:
    def test_builtin_cases_loaded(self) -> None:
        assert len(CASES) >= 17
        ids = [c.id for c in CASES]
        assert len(ids) == len(set(ids))

    def test_duplicate_id_rejected(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "dup.json"
        bad_file.write_text(
            json.dumps(
                [
                    {"id": "dup", "text": "a", "check": "shape", "category": "short"},
                    {"id": "dup", "text": "b", "check": "shape", "category": "short"},
                ]
            ),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="重复"):
            _load_cases(bad_file)

    def test_unknown_field_rejected(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "unknown.json"
        bad_file.write_text(
            json.dumps(
                [
                    {
                        "id": "c1",
                        "text": "a",
                        "check": "shape",
                        "category": "short",
                        "extra": 1,
                    }
                ]
            ),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="未知字段"):
            _load_cases(bad_file)
