import os
import json
import logging
from typing import List, Dict, Any, Optional,Union
from openai import OpenAI
from dotenv import load_dotenv
import re

# 加载环境变量（建议将 OPENAI_API_KEY 写入 .env）
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

client = OpenAI(
    api_key=os.getenv("MINIMAX_API_KEY"),
    base_url="https://api.minimaxi.com/v1",
)


def extract_json_from_response(text: str) -> Any:
    """
    从可能包含 Markdown、<think> 等额外内容的响应中提取纯 JSON
    返回解析后的 Python 对象，如果找不到则抛出 ValueError
    """
    # 1. 尝试提取 Markdown 代码块中的 json
    code_block_match = re.search(r'```json\s*(\{.*?\})\s*```', text, re.DOTALL)
    if not code_block_match:
        # 可能没有代码块标记，尝试匹配最外层花括号或方括号
        # 尝试匹配 JSON 对象 {...} 或数组 [...]
        # 使用贪婪匹配，从第一个 { 或 [ 开始，到最后一个 } 或 ] 结束
        match = re.search(r'(\{.*\}|\[.*\])', text, re.DOTALL)
        if match:
            json_str = match.group(1)
        else:
            raise ValueError("未找到有效的 JSON 结构")
    else:
        json_str = code_block_match.group(1)
    
    # 2. 尝试解析 JSON，如果失败则抛出异常
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        # 可能包含换行或多余字符，再尝试清理
        cleaned = re.sub(r'[\x00-\x1f\x7f]', '', json_str)  # 移除控制字符
        return json.loads(cleaned)




# ==================== 公共辅助函数 ====================
def validate_relationship_output(data: Any) -> List[Dict[str, str]]:
    """校验并标准化输出为 List[{source, relation, target}]"""
    if not isinstance(data, list):
        raise ValueError("输出应为列表")
    
    validated = []
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("每个元素应为字典")
        # 补全缺失字段
        source = item.get("source", "")
        relation = item.get("relation", "")
        target = item.get("target", "")
        if not source or not target:
            logger.warning(f"忽略缺少source或target的条目: {item}")
            continue
        validated.append({"source": source.strip(), "relation": relation.strip(), "target": target.strip()})
    
    return validated


# ==================== 方法1：Tool Call（函数调用） ====================
TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "extract_relationships",
        "description": "从中文句子中提取人物之间的情感关系",
        "parameters": {
            "type": "object",
            "properties": {
                "relationships": {
                    "type": "array",
                    "description": "关系列表，每个元素包含来源人物、关系类型、目标人物",
                    "items": {
                        "type": "object",
                        "properties": {
                            "source": {"type": "string", "description": "关系中的主体（主动方）"},
                            "relation": {"type": "string", "description": "关系类型，如'喜欢'、'爱慕'、'讨厌'等"},
                            "target": {"type": "string", "description": "关系中的客体（被动方）"}
                        },
                        "required": ["source", "relation", "target"],
                        "additionalProperties": False
                    }
                }
            },
            "required": ["relationships"],
            "additionalProperties": False
        }
    }
}

def analyze_with_tool_call(text: str, model: str = "MiniMax-M3") -> List[Dict[str, str]]:
    """
    使用工具调用（函数调用）方式提取关系
    """
    try:
        logger.info(f"[Tool Call] 处理文本: {text}")
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是一个情感分析专家，擅长从中文文本中提取人物关系。请根据用户输入调用工具。"},
                {"role": "user", "content": text}
            ],
            tools=[TOOL_SCHEMA],
            tool_choice={"type": "function", "function": {"name": "extract_relationships"}},  # 强制调用
            temperature=0.1,  # 低温度保证确定性
        )

        message = response.choices[0].message
        # 检查是否有工具调用
        if not message.tool_calls:
            logger.warning("模型未调用工具，回退尝试解析文本内容")
            # 可做降级：直接要求模型返回JSON（但为了演示，抛出异常）
            raise RuntimeError("模型未按预期调用工具")

        tool_call = message.tool_calls[0]
        if tool_call.function.name != "extract_relationships":
            raise RuntimeError(f"调用了错误的工具: {tool_call.function.name}")

        # 解析工具参数（已经是JSON字符串）
        args = json.loads(tool_call.function.arguments)
        relationships = args.get("relationships", [])
        logger.info(f"[Tool Call] 原始输出: {relationships}")

        # 校验并返回
        return validate_relationship_output(relationships)

    except json.JSONDecodeError as e:
        logger.error(f"JSON解析失败: {e}")
        raise
    except Exception as e:
        logger.error(f"Tool Call 失败: {e}")
        raise


# ==================== 方法2：JSON Mode ====================
def analyze_with_json_mode(text: str, model: str = "abab6.5s-chat") -> List[Dict[str, str]]:
    try:
        logger.info(f"[JSON Mode] 处理文本: {text}")
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": (
                    "你是一个情感分析专家。请从用户输入的中文句子中提取所有人物关系，"
                    "并以**严格的JSON数组格式**返回，每个元素包含三个字段：source（主体）、relation（关系类型）、target（客体）。"
                    "不要输出任何其他内容，只输出JSON数组，不要包含Markdown代码块或解释。"
                )},
                {"role": "user", "content": text}
            ],
            temperature=0.1,
            # 注意：MiniMax 可能不支持 response_format，因此删除该参数
        )
        raw_content = response.choices[0].message.content
        logger.info(f"[JSON Mode] 原始响应: {raw_content}")

        # 尝试提取 JSON
        data = extract_json_from_response(raw_content)

        # 后续处理同之前
        if isinstance(data, dict):
            for key in ["relationships", "data", "result"]:
                if key in data and isinstance(data[key], list):
                    data = data[key]
                    break
            if isinstance(data, dict) and all(k in data for k in ("source", "relation", "target")):
                data = [data]
        if not isinstance(data, list):
            data = [data] if isinstance(data, dict) else []

        return validate_relationship_output(data)

    except Exception as e:
        logger.error(f"JSON Mode 失败: {e}")
        raise

# ==================== 测试入口 ====================
if __name__ == "__main__":
    input_text = "小明喜欢小姚，但是小姚喜欢小王"
    
    print("=" * 50)
    print("输入文本:", input_text)
    print("=" * 50)
    
    try:
        result_tool = analyze_with_tool_call(input_text)
        print("\n[Tool Call 结果]")
        print(json.dumps(result_tool, ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"\n[Tool Call 错误] {e}")

    try:
        result_json = analyze_with_json_mode(input_text)
        print("\n[JSON Mode 结果]")
        print(json.dumps(result_json, ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"\n[JSON Mode 错误] {e}")
