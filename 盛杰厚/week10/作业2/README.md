# 作业2：自定义 MCP 工具 + Agent 调用

基于「兼容 OpenAI-Agent 的 MCP 代码」思路：自己写一个 MCP server，新增 3 个 MCP 工具，并让 `openai-agents` 的 Agent 通过 **SSE（HTTP + SSE）**（`MCPServerSse`）调用它们。

## 3 个 MCP 工具

| 工具 | 说明 |
|------|------|
| `get_current_time(timezone)` | 获取指定时区的当前时间（默认北京时间） |
| `calculate(expression)` | 安全计算四则运算表达式（AST 白名单，规避 eval 注入） |
| `text_stats(text)` | 统计文本的字符数 / 单词数 / 行数 |

## 运行方式

`agent_main.py` 会自动检测并后台拉起 `mcp_server.py`（跑完自动回收），所以一条命令即可：

```bash
export OPENAI_API_KEY="你的 DeepSeek Key"
python agent_main.py "帮我算 (1234+5678)*2，再告诉我现在北京时间，最后统计 'hello world, welcome to MCP' 有几个单词"
```

也可以手动分两步（先起 server，再跑 agent；此时 agent 不会重复拉起）：

```bash
# 终端一：启动 MCP server（SSE，默认监听 http://127.0.0.1:8001/sse）
python mcp_server.py
```

```bash
# 终端二：设置 DeepSeek Key 并运行 agent
export OPENAI_API_KEY="你的 DeepSeek Key"
python agent_main.py "帮我算 (1234+5678)*2，再告诉我现在北京时间，最后统计 'hello world, welcome to MCP' 有几个单词"
```

## 运行结果示例

Agent 会自动判断并依次调用 3 个 MCP 工具，然后汇总：

```
1. (1234+5678)*2 = 13824.0
2. Asia/Shanghai 当前时间：2026-10-15 ...
3. "hello world, welcome to MCP" 共 5 个单词
```

## 说明

- `mcp_server.py` 用 `mcp.server.fastmcp.FastMCP` 定义工具，以 `transport="sse"` 启动（默认 `http://127.0.0.1:8001/sse`，端口可用环境变量 `MCP_PORT` 覆盖；注：8000 已被本机 common-agent 占用）。
- `agent_main.py` 用 `MCPServerSse(name=..., params={"url": ...})` 连接 SSE 服务；若检测不到 server 会自动后台拉起 `mcp_server.py` 并在结束后回收（URL 可用环境变量 `MCP_SERVER_URL` 覆盖）。HTTP 客户端通过 `httpx_client_factory` 设置 `trust_env=False`，绕过本机 Clash 系统代理（否则连 127.0.0.1 也会被代理转发导致 502）。
- 模型默认走 DeepSeek（`chat_completions` 协议），可用环境变量 `OPENAI_BASE_URL` / `OPENAI_MODEL` 覆盖。
- 依赖见 `requirements.txt`。
