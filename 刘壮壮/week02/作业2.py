"""
作业二：人物关系助手

DeepSeek 的 Tools（Function Calling）与 JSON Mode 不宜在同一次请求里叠用：
  - Tools：结构化参数在 tool_calls.arguments 里，最终 content 是自然语言
  - JSON Mode：强制 content 为合法 JSON，适合「先抽结构再本地执行」

因此本文件提供两种实现，通过 MODE 切换（运行时也可输入 mode tools / mode json）。
"""

import os
from dotenv import load_dotenv
from openai import OpenAI
import json

load_dotenv()

api_key = os.getenv("DEEPSEEK_API_KEY")

client = OpenAI(
    api_key=api_key,
    base_url="https://api.deepseek.com")

# 运行模式： "tools" | "json"
MODE = "json"

# source: 小明；relation：喜欢/不喜欢；target：小王
# 保存人物关系
# 结构：relations[source][target] = relation
relations: dict = {}


# ─────────────────────────────────────────────
# 业务函数（两种模式共用）
# ─────────────────────────────────────────────

def find_relationship(person1: str, person2: str = None) -> str:
    if person2:
        # 查两个人的关系
        r1 = relations.get(person1, {})
        r2 = relations.get(person2, {})
        parts = []
        if r1 and r1.get(person2):
            parts.append(f"{person1} {r1.get(person2)} {person2}")
        if r2 and r2.get(person1):
            parts.append(f"{person2} {r2.get(person1)} {person1}")
        return "；".join(parts) if parts else f"未找到 {person1} 与 {person2} 的关系"
    # 查一个人的关系
    outs = relations.get(person1, {})
    if outs:
        return "；".join(f"{person1} {rel} {t}" for t, rel in outs.items())

    return f"未找到 {person1} 的关系"


def save_relationship(source: str, relation: str, target: str) -> str:
    if source not in relations:
        relations[source] = {}
    relations[source][target] = relation
    return f"保存 {source} {relation} {target} 关系成功"


TOOLS_REGISTRY_MAP: dict = {
    "find_relationship": find_relationship,
    "save_relationship": save_relationship,
}


# ─────────────────────────────────────────────
# 方式一：Tools / Function Calling
# ─────────────────────────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "find_relationship",
            "description": "仅在用户询问/查询关系时使用。例如：「小红和小明什么关系？」「小红喜欢谁？」。不要用于用户陈述关系事实（如「小红喜欢小明」）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "person1": {
                        "type": "string",
                        "description": "人物名称",
                    },
                    "person2": {
                        "type": "string",
                        "description": "人物名称",
                    },
                },
                "required": ["person1"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_relationship",
            "description": "当用户陈述、告知或要求记录关系时使用。例如：「小红喜欢小明」「小王不喜欢小李」。从陈述中抽取 source、relation、target 并保存。",
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "description": "人物名称，源人物",
                    },
                    "relation": {
                        "type": "string",
                        "description": "关系，如 喜欢、不喜欢",
                    },
                    "target": {
                        "type": "string",
                        "description": "人物名称，目标人物",
                    },
                },
                "required": ["source", "relation", "target"],
            },
        },
    },
]

TOOLS_SYSTEM_PROMPT = """你是人物关系助手。根据用户意图选择工具：
- 用户陈述/告知关系（如「小红喜欢小明」「把小明和小王设为朋友」）→ 必须调用 save_relationship
- 用户提问/查询（如「小红喜欢谁」「小红和小明什么关系」）→ 调用 find_relationship
不要把陈述句当成查询。"""


def run_tool_call(tool_call) -> str:
    tool_name = tool_call.function.name
    tool_args = json.loads(tool_call.function.arguments)
    result = TOOLS_REGISTRY_MAP[tool_name](**tool_args)
    return result if result else "工具调用失败"


MAX_TOOL_ROUNDS = 5


def handle_with_tools(messages: list, prompt: str) -> None:
    """方式一：Function Calling，模型通过 tool_calls 传结构化参数。"""
    messages.append({"role": "user", "content": prompt})

    for _ in range(MAX_TOOL_ROUNDS):
        response = client.chat.completions.create(
            model="deepseek-v4-flash",
            messages=messages,
            tools=TOOLS,
            temperature=0.0,
        )
        msg = response.choices[0].message

        if msg.tool_calls:
            messages.append(msg)
            for tool_call in msg.tool_calls:
                tool_result = run_tool_call(tool_call)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": tool_result,
                })
            continue

        messages.append({"role": "assistant", "content": msg.content})
        print(msg.content)
        break
    else:
        print(f"已达到最大工具调用轮次（{MAX_TOOL_ROUNDS}），停止本次请求。")


# ─────────────────────────────────────────────
# 方式二：JSON Mode（response_format=json_object）
# ─────────────────────────────────────────────

JSON_SYSTEM_PROMPT = """你是人物关系助手。请根据用户意图，以 JSON 格式输出结构化结果（不要输出其它文字）。

字段说明：
- action: "save_relationship" | "find_relationship" | "chat"
  - 用户陈述/告知关系（如「小红喜欢小明」）→ save_relationship
  - 用户提问/查询关系（如「小红喜欢谁」）→ find_relationship
  - 其它闲聊 → chat
- arguments: 调用参数对象
  - save_relationship 时：{"source": "...", "relation": "...", "target": "..."}
  - find_relationship 时：{"person1": "..."} 或 {"person1": "...", "person2": "..."}
  - chat 时：{}
- reply: 给用户看的自然语言回复（save/chat 可直接写；find 时先占位，程序会把查询结果填回）

JSON 输出示例：
{"action": "save_relationship", "arguments": {"source": "小红", "relation": "喜欢", "target": "小明"}, "reply": "已记下：小红喜欢小明"}

{"action": "find_relationship", "arguments": {"person1": "小红", "person2": "小明"}, "reply": ""}

{"action": "chat", "arguments": {}, "reply": "你好，我可以帮你记录和查询人物关系。"}
"""


MAX_JSON_RETRIES = 3

VALID_ACTIONS = {"save_relationship", "find_relationship", "chat"}

JSON_REPAIR_PROMPT = """你上一次的输出格式有误，请按系统要求重新输出合法 JSON（不要输出其它文字）。

错误信息：
{error}

错误输出：
{bad_content}

正确格式要求：
- 必须是单个 JSON 对象
- 字段：action、arguments、reply
- action 只能是：save_relationship | find_relationship | chat
- save_relationship 的 arguments：source、relation、target（均为字符串）
- find_relationship 的 arguments：person1（必填），person2（可选）
- chat 的 arguments：{{}}
- reply：字符串
"""


def strip_removable_format(text: str) -> str:
    """去掉可容忍的包装格式：首尾空白、markdown 代码块围栏。"""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # ```json / ```JSON / ```
        first_nl = cleaned.find("\n")
        if first_nl != -1:
            cleaned = cleaned[first_nl + 1 :]
        else:
            cleaned = cleaned.lstrip("`")
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:]
        cleaned = cleaned.rstrip()
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].rstrip()
    return cleaned.strip()


def safe_json_parse(text: str) -> tuple[dict | None, str | None]:
    """解析 JSON；可去除的包装去掉后能解析则视为成功。

    Returns:
        (data, error)：成功时 error 为 None；失败时 data 为 None。
    """
    if not text or not text.strip():
        return None, "模型返回了空 content"

    candidates = [text.strip(), strip_removable_format(text)]
    # 去重但保序
    seen = set()
    unique_candidates = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            unique_candidates.append(c)

    last_err = None
    for candidate in unique_candidates:
        try:
            data = json.loads(candidate)
            if not isinstance(data, dict):
                return None, f"根节点必须是 JSON 对象，实际类型: {type(data).__name__}"
            return data, None
        except json.JSONDecodeError as e:
            last_err = str(e)

    return None, f"JSON 解析失败: {last_err}"


def validate_json_payload(data: dict) -> str | None:
    """校验业务 JSON 结构。通过返回 None，否则返回错误说明。"""
    if "action" not in data:
        return "缺少字段 action"
    action = data["action"]
    if action not in VALID_ACTIONS:
        return f"action 非法: {action!r}，允许值: {sorted(VALID_ACTIONS)}"

    if "arguments" not in data:
        return "缺少字段 arguments"
    args = data["arguments"]
    if not isinstance(args, dict):
        return f"arguments 必须是对象，实际类型: {type(args).__name__}"

    if "reply" not in data:
        return "缺少字段 reply"
    if not isinstance(data["reply"], str):
        return f"reply 必须是字符串，实际类型: {type(data['reply']).__name__}"

    if action == "save_relationship":
        required = ("source", "relation", "target")
        missing = [k for k in required if k not in args or not str(args.get(k, "")).strip()]
        if missing:
            return f"save_relationship 缺少/为空参数: {missing}"
        for k in required:
            if not isinstance(args[k], str):
                return f"save_relationship 参数 {k} 必须是字符串"
    elif action == "find_relationship":
        if "person1" not in args or not str(args.get("person1", "")).strip():
            return "find_relationship 缺少/为空参数: person1"
        if not isinstance(args["person1"], str):
            return "find_relationship 参数 person1 必须是字符串"
        if "person2" in args and args["person2"] is not None and not isinstance(args["person2"], str):
            return "find_relationship 参数 person2 必须是字符串或省略"
    elif action == "chat":
        # chat 允许空对象；多出来的键可忽略
        pass

    return None


def parse_and_validate_json(text: str) -> tuple[dict | None, str | None]:
    """解析 + 结构校验。成功返回 (data, None)，失败返回 (None, error)。"""
    data, err = safe_json_parse(text)
    if err:
        return None, err
    schema_err = validate_json_payload(data)
    if schema_err:
        return None, schema_err
    return data, None


def request_json_completion(messages: list) -> str:
    response = client.chat.completions.create(
        model="deepseek-v4-flash",
        messages=messages,
        response_format={"type": "json_object"},
        max_tokens=512,
        temperature=0.0,
    )
    return response.choices[0].message.content or ""


def handle_with_json(messages: list, prompt: str) -> None:
    """方式二：JSON Mode，模型输出 JSON，本地解析后再调用同一套业务函数。

    流程：解析（可剥离 markdown 等无关包装）→ 结构校验 → 失败则让 LLM 修复，最多 MAX_JSON_RETRIES 次。
    修复轮次只在临时副本上进行，避免污染长期对话上下文。
    """
    messages.append({"role": "user", "content": prompt})
    # 修复用临时上下文，成功后再把最终结果写回 messages
    work_messages = list(messages)

    content = request_json_completion(work_messages)
    data, error = parse_and_validate_json(content)

    for attempt in range(1, MAX_JSON_RETRIES + 1):
        if data is not None:
            break
        print(f"⚠️  输出格式校验失败（第 {attempt}/{MAX_JSON_RETRIES} 次修复）: {error}")
        print(f"原始内容: {content[:200]}")
        work_messages.append({"role": "assistant", "content": content})
        work_messages.append({
            "role": "user",
            "content": JSON_REPAIR_PROMPT.format(error=error, bad_content=content),
        })
        content = request_json_completion(work_messages)
        data, error = parse_and_validate_json(content)

    if data is None:
        print(f"未能得到合法 JSON（已重试 {MAX_JSON_RETRIES} 次），跳过本次请求。")
        print(f"最后错误: {error}")
        # 仍写入 assistant，避免上下文断裂
        messages.append({"role": "assistant", "content": content or ""})
        return

    action = data.get("action", "chat")
    args = data.get("arguments") or {}
    reply = data.get("reply") or ""

    if action in TOOLS_REGISTRY_MAP:
        try:
            tool_result = TOOLS_REGISTRY_MAP[action](**args)
        except TypeError as e:
            tool_result = f"参数错误: {e}"
        # 查询结果优先展示；保存类可用模型 reply，没有则用工具返回
        if action == "find_relationship":
            final = tool_result
        else:
            final = reply or tool_result
        print(final)
        messages.append({
            "role": "assistant",
            "content": json.dumps(
                {**data, "tool_result": tool_result, "final": final},
                ensure_ascii=False,
            ),
        })
    else:
        print(reply or content)
        messages.append({
            "role": "assistant",
            "content": json.dumps(data, ensure_ascii=False),
        })


# ─────────────────────────────────────────────
# 主循环
# ─────────────────────────────────────────────

def make_messages() -> list:
    system = TOOLS_SYSTEM_PROMPT if MODE == "tools" else JSON_SYSTEM_PROMPT
    return [{"role": "system", "content": system}]

# 初始化系统提示词
messages = make_messages()

print(f"当前模式: {MODE}（输入 mode tools / mode json 切换）")
print("命令: help | quit | clear | mode tools | mode json")

while True:
    prompt = input("用户输入：")
    if prompt == "quit":
        break
    if prompt == "help":
        print("help: 显示帮助信息")
        print("quit: 退出程序")
        print("clear: 清空对话上下文")
        print("mode tools: 切换到 Function Calling 实现")
        print("mode json:  切换到 JSON Mode 实现")
        print(f"当前模式: {MODE}")
        continue
    if prompt == "clear":
        messages = make_messages()
        print("已清空上下文")
        continue
    if prompt in ("mode tools", "mode json"):
        MODE = prompt.split()[1]
        messages = make_messages()
        print(f"已切换到 {MODE} 模式，并清空上下文")
        continue

    if MODE == "tools":
        handle_with_tools(messages, prompt)
    else:
        handle_with_json(messages, prompt)
