# 王鑫炜 · 第10周作业：Agent 搭建与 MCP 应用

根据课堂 `Week10/note.txt` 末尾的两项要求实现。

## 文件说明

| 文件 | 用途 |
| --- | --- |
| `homework1_translate.py` | 作业一：语言识别、双向翻译和 JSON 校验 |
| `homework2_server.py` | 作业二：提供 5 个 MCP 工具，其中 3 个为新增 |
| `homework2_client.py` | 通过 OpenAI Agents SDK 发现、选择、调用 MCP 工具 |
| `config.py` | 共用模型配置和连接管理 |
| `test_homework.py` | 无密钥测试，包含实际 SSE 连接与 Agent 工具调用链路 |
| `.env.example` | 配置模板，不含真实密钥 |

## 环境准备

使用 Python 3.12。进入本目录后执行：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

编辑 `.env`，填入自己的 `OPENAI_API_KEY`。默认沿用课堂的 DashScope 兼容接口和 `qwen-max`；也可同时修改 `OPENAI_BASE_URL`、`OPENAI_MODEL`，换成支持 Chat Completions 的接口。作业二要求模型支持 function calling。配置从代码所在目录读取，系统环境变量优先。

## 作业一：语言识别与翻译

```bash
python homework1_translate.py '我正在学习智能体开发。'
python homework1_translate.py 'Hello, how are you?'
python homework1_translate.py 'こんにちは、世界！'
```

也可以从标准输入读取多行文本：

```bash
printf 'Hello world!' | python homework1_translate.py
```

输出格式示意（实际翻译措辞取决于模型）：

```json
{
  "query_input": "Hello, how are you?",
  "language": "英语",
  "result": "你好，你好吗？"
}
```

规则：中文（包括繁体中文）翻译为英文，其他语言翻译为简体中文。混合文本按主要语言判断。语言识别由模型完成，不以“包含汉字”作为中文判据，因为日语也使用汉字。

执行过程：输入检查 → `Agent` 识别和翻译 → `Runner.run` → Pydantic 严格校验 → 输出 JSON。默认通过提示词要求 JSON，并在本地检查字段、类型、非空内容和原文是否一致；格式不合格时最多再请求一次。兼容接口若支持 JSON Schema，可添加 `--structured`，启用 `output_type=TranslationResult`。

纯数字、符号、空白以及超过 10000 字符的输入会报错。JSON 校验能保证格式，不能证明语种识别和翻译语义一定正确；歧义短句、混合语言仍需人工核对。

## 作业二：新增 3 个 MCP 工具并由 Agent 调用

基于课堂 `2-兼容OpenAI-Agent` 的 FastMCP 服务端和 `MCPServerSse` 客户端结构实现。

终端一启动服务：

```bash
source .venv/bin/activate
python homework2_server.py
```

终端二运行客户端：

```bash
source .venv/bin/activate
python homework2_client.py
```

默认依次演示三个新增工具，每次显示可用工具、用户问题、实际工具调用参数、工具返回和最终回答。自定义问题：

```bash
python homework2_client.py '请计算 12.5 乘 8，并计算 2024-02-28 到 2024-03-01 的日期间隔。'
python homework2_client.py '请统计文本：你好，MCP! Hello world'
```

| 新增工具 | 功能 | 示例结果 |
| --- | --- | --- |
| `calculate` | 两个十进制字符串的加减乘除，使用 Decimal | `0.1 + 0.2 = 0.3` |
| `date_difference` | 两个 YYYY-MM-DD 日期之间的有符号天数 | 2026-10-01 → 2026-10-15 为 14 天 |
| `text_statistics` | 统计字符、非空白字符、基础汉字和英文词数 | 示例文本共 19 字符、17 个非空白字符、2 个汉字、3 个英文词 |

计算工具不使用 `eval`，操作数最长 50 字符；除法最多保留 110 位有效数字，循环小数会舍入。日期间隔是结束日期减开始日期，同日为 0，倒序为负数。文本“字符”按 Python Unicode 码点计数，不等同于视觉字形数；汉字统计范围为 U+4E00–U+9FFF，英文词按连续英文字母及内部撇号匹配，不是通用语言分词。

保留课堂工具 `roll_dice`、`get_news`：骰子取值修正为 1～6；新闻明确标注为静态演示，未接入真实新闻源。

调用链路：

```text
用户问题 → Agent 获取 MCP 工具清单 → 模型选择工具并生成参数
        → SDK 经 SSE 调用本地 MCP 服务 → 工具执行并返回
        → SDK 将工具结果传回模型 → 最终回答
```

工具选择发生在模型/Agent 一侧；MCP 提供工具发现与调用协议，本身不负责推理。默认监听 `127.0.0.1:8000`。如端口占用：

```bash
python homework2_server.py --port 8001
python homework2_client.py --url http://127.0.0.1:8001/sse
```

## 验证

2026-10-15 验证记录：Python 3.12.14、openai-agents 0.19.4、FastMCP 3.4.8，11 项测试全部通过。当前运行环境没有配置真实模型 API Key，尚未进行真实模型验收。

```bash
python -m unittest -v test_homework
```

测试不需要真实 API Key。模型的 HTTP 响应用固定数据模拟，但真实执行 Agents SDK、JSON 校验、MCP 工具发现、工具函数，以及子进程服务端上的 SSE 调用。它验证程序和协议链路，不代表已验证真实模型的翻译质量或自主工具选择能力。

真实模型验收：配置 `.env` 后，运行上面的中文、英语、日语翻译命令，检查语种和翻译方向；运行 `python homework2_client.py`，检查三个问题分别出现 `calculate`、`date_difference`、`text_statistics` 的调用记录，返回值与表格一致。

## 参考

- 课程示例：`Week10/2-fastmcp使用/2-兼容OpenAI-Agent/client.py` 和 `server.py`。
- [OpenAI 官方 Agent 定义说明](https://developers.openai.com/api/docs/guides/agents/define-agents)：Agent 的模型、指令、工具和结构化输出配置。
- [FastMCP 测试说明](https://gofastmcp.com/servers/testing)：通过客户端验证服务端工具。
