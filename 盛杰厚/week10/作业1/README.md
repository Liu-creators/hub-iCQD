# 作业1：语种识别 + 翻译助手（OpenAI Agents 框架）

用 OpenAI 官方 `openai-agents` 框架实现：输入文本 → 判断语种 → 非中文翻中文 / 中文翻英文 → 输出固定 JSON。

## 运行方式

```bash
# 先设置 DeepSeek API Key（也可 export 到环境变量）
export OPENAI_API_KEY="你的 DeepSeek Key"

# 中文 -> 英文
python language_agent.py "你好，世界"

# 英文 -> 中文
python language_agent.py "Hello, how are you?"

# 不传参数则交互式输入
python language_agent.py
```

## 输出示例

```json
{
    "query_input": "你好，世界",
    "language": "中文",
    "result": "Hello, world"
}
```

## 说明

- Agent 让模型直接输出 JSON 文本，再用 `pydantic` 模型 `TranslationResult` 校验，字段严格为 `query_input` / `language` / `result`。
- **为什么不直接用 `Agent(output_type=TranslationResult)` 结构化输出**：openai-agents 的结构化输出会走 `response_format`（json_schema），而 DeepSeek 端点不支持，会报 `This response_format type is unavailable now`。因此改为「提示词约束输出 JSON + Pydantic 校验兜底」。
- 通过 `ModelSettings(extra_body={"thinking": {"type": "disabled"}})` 关闭 DeepSeek 推理模型的思考过程，让输出更干净。
- 模型默认走 DeepSeek（OpenAI 兼容，`chat_completions` 协议），可用环境变量覆盖：
  - `OPENAI_BASE_URL`（默认 `https://api.deepseek.com`）
  - `OPENAI_MODEL`（默认 `deepseek-flash`）
