from translator.models import TranslateResult
from translator.multi import translate as translate_multi
from translator.single import translate as translate_single
from translator.validators import validate_text

__all__ = ["TranslateResult", "translate", "translate_multi", "translate_single"]


def translate(text: str, mode: str = "single") -> TranslateResult:
    """mode 为 single 或 multi。调用模型前需要先执行 client.setup_client()。"""
    text = validate_text(text)
    if mode == "single":
        return translate_single(text)
    if mode == "multi":
        return translate_multi(text)
    raise ValueError(f"unknown mode: {mode}")
