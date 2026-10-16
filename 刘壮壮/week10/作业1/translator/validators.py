MAX_TEXT_LENGTH = 1000

def validate_text(text: str) -> str:
    """第一层：硬规则检查(空字符， 超长文本)"""
    if not isinstance(text, str):
        raise TypeError(f"输入必须为字符串，收到：{type(text).__name__}")
    cleaned = text.strip()
    if not cleaned:
        raise ValueError("输入不能为空")
    if len(cleaned) > MAX_TEXT_LENGTH:
        raise ValueError(f"输入超长，最大长度为{MAX_TEXT_LENGTH}字符")
    
    return text