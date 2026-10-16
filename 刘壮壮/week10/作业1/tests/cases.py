import json
from dataclasses import dataclass
from pathlib import Path

_DATA_PATH = Path(__file__).with_name("cases.json")
_FIELDS = {"id", "text", "check", "category", "expected_language", "expected_target", "hijack_output"}
_WITH_TARGET = {"direction", "injection"}
_WITHOUT_TARGET = {"shape", "blocked"}
_TARGETS = {"en", "zh"}


@dataclass(frozen=True)
class TranslateCase:
    id: str
    text: str
    check: str
    category: str
    expected_language: str | None = None
    expected_target: str | None = None
    hijack_output: str | None = None


def _nonempty(item: dict, key: str, label: str) -> str:
    value = item.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise ValueError(f"{label} 的 {key} 必须是非空字符串")


def _load_cases(path: Path) -> list[TranslateCase]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{path.name} 必须是非空数组")

    cases: list[TranslateCase] = []
    seen: set[str] = set()
    for index, item in enumerate(raw, start=1):
        label = f"{path.name} 第 {index} 条"
        if not isinstance(item, dict):
            raise ValueError(f"{label} 必须是对象")
        unknown = set(item) - _FIELDS
        if unknown:
            names = ", ".join(sorted(unknown))
            raise ValueError(f"{label} 有未知字段: {names}")

        case_id = _nonempty(item, "id", label)
        if case_id in seen:
            raise ValueError(f"{path.name} 用例 id 重复: {case_id}")
        seen.add(case_id)

        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"{label} 的 text 必须是非空字符串")
        check = _nonempty(item, "check", label)
        category = _nonempty(item, "category", label)
        language = item.get("expected_language")
        target = item.get("expected_target")
        hijack = item.get("hijack_output")

        if check in _WITH_TARGET:
            language = _nonempty(item, "expected_language", label)
            if target not in _TARGETS:
                raise ValueError(f"{label} 的 expected_target 只能是 en 或 zh")
        elif check in _WITHOUT_TARGET:
            if language is not None or target is not None:
                raise ValueError(f"{label} 是 {check}，不写 expected_language 和 expected_target")
            language = None
            target = None
        else:
            raise ValueError(f"{label} 的 check 只能是 direction、injection、blocked 或 shape")

        if check == "injection" and hijack is not None:
            hijack = _nonempty(item, "hijack_output", label)
        elif hijack is not None:
            raise ValueError(f"{label} 只有 injection 用例可以写 hijack_output")

        cases.append(
            TranslateCase(
                id=case_id,
                text=text,
                check=check,
                category=category,
                expected_language=language,
                expected_target=target,
                hijack_output=hijack,
            )
        )
    return cases


# 空字符串不放进 cases.json。translate() 会在调用模型之前拒绝它。
CASES = _load_cases(_DATA_PATH)
