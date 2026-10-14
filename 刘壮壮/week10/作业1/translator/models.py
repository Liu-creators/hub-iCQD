import re

from pydantic import BaseModel, Field


def normalize_language(language: str) -> str:
    """规范化语言代码：去空白、转小写，并截掉 -CN 或 _TW 等区域后缀。"""
    return re.split(r"[-_]", language.strip().lower())[0]


class LLMTranslateOutput(BaseModel):
    """单 agent 的模型输出：语言代码和译文一起返回。"""

    language: str = Field(description="ISO 639-1 code, 如 zh/en/ja")
    result: str = Field(description="翻译结果")


class LangResult(BaseModel):
    """多 agent 里语言检测这一步的模型输出。"""

    language: str = Field(description="ISO 639-1, 如 zh/en/ja")


class TranslateResult(BaseModel):
    """两种方案统一的返回。"""

    query_input: str
    language: str
    result: str
