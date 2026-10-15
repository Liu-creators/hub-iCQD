"""无需真实 API Key：模拟模型 HTTP 响应，但执行真实 SDK 和本地 SSE/MCP。"""
import asyncio
import io
import json
import socket
import sys
import time
import unittest
from contextlib import asynccontextmanager, redirect_stdout
from pathlib import Path

import httpx
from agents import OpenAIChatCompletionsModel, set_tracing_disabled
from agents.mcp import MCPServerSse
from fastmcp import Client
from openai import AsyncOpenAI

from homework1_translate import translate
from homework2_client import print_run, run_query
from homework2_server import mcp

set_tracing_disabled(True)


@asynccontextmanager
async def mock_model(messages):
    """仅替换模型网络接口，不替换 Runner、工具发现或 MCP 调用。"""
    pending = iter(messages)
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        message = next(pending)
        return httpx.Response(200, json={
            "id": "chatcmpl-test", "object": "chat.completion", "created": 0,
            "model": "test-model", "choices": [{
                "index": 0, "message": message,
                "finish_reason": "tool_calls" if message.get("tool_calls") else "stop",
            }], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        async with AsyncOpenAI(api_key="test-only", base_url="https://model.invalid/v1", http_client=http) as client:
            yield OpenAIChatCompletionsModel(model="test-model", openai_client=client), requests


def answer(content):
    return {"role": "assistant", "content": content}


class TranslationTests(unittest.IsolatedAsyncioTestCase):
    async def test_three_languages_and_preserve_input(self):
        for source, language, target in [
            (" Hello world!\n", "英语", "你好，世界！"),
            ("我正在学习 MCP。", "中文", "I am learning MCP."),
            ("こんにちは", "日语", "你好"),
        ]:
            with self.subTest(language=language):
                payload = {"query_input": source, "language": language, "result": target}
                async with mock_model([answer(json.dumps(payload))]) as (model, requests):
                    result = await translate(source, model)
                    self.assertEqual(result.model_dump(), payload)
                    self.assertEqual(len(requests), 1)

    async def test_structured_output(self):
        payload = {"query_input": "Hello", "language": "英语", "result": "你好"}
        async with mock_model([answer(json.dumps(payload))]) as (model, requests):
            self.assertEqual((await translate("Hello", model, structured=True)).result, "你好")
            self.assertEqual(requests[0]["response_format"]["type"], "json_schema")

    async def test_invalid_output_retries(self):
        good = {"query_input": "Hello", "language": "英语", "result": "你好"}
        for bad in ["not JSON", json.dumps({**good, "extra": 1}),
                    json.dumps({**good, "query_input": "modified"}),
                    json.dumps({**good, "result": " "})]:
            with self.subTest(bad=bad):
                async with mock_model([answer(bad), answer(json.dumps(good))]) as (model, requests):
                    self.assertEqual((await translate("Hello", model)).result, "你好")
                    self.assertEqual(len(requests), 2)

    async def test_repeated_invalid_output_fails(self):
        async with mock_model([answer("bad"), answer("bad")]) as (model, _):
            with self.assertRaisesRegex(ValueError, "连续两次"):
                await translate("Hello", model)

    async def test_invalid_input_never_calls_model(self):
        async with mock_model([]) as (model, requests):
            for text in ["", "  ", "123!?", "a" * 10001]:
                with self.subTest(text=text[:20]), self.assertRaises(ValueError):
                    await translate(text, model)
            self.assertEqual(requests, [])


class ToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_discovery(self):
        async with Client(mcp) as client:
            self.assertEqual({t.name for t in await client.list_tools()}, {
                "roll_dice", "get_news", "calculate", "date_difference", "text_statistics"
            })

    async def test_decimal_calculations(self):
        async with Client(mcp) as client:
            for a, op, b, expected in [("0.1", "+", "0.2", "0.3"), ("1", "-", "3", "-2"),
                                       ("1.5", "*", "4", "6.0"), ("3", "/", "2", "1.5")]:
                with self.subTest(op=op):
                    result = await client.call_tool("calculate", {"a": a, "operator": op, "b": b})
                    self.assertEqual(result.data["result"], expected)
            for args in [{"a": "1", "operator": "/", "b": "0"},
                         {"a": "NaN", "operator": "+", "b": "1"}]:
                result = await client.call_tool("calculate", args, raise_on_error=False)
                self.assertTrue(result.is_error)

    async def test_dates_and_invalid_date(self):
        async with Client(mcp) as client:
            for start, end, days in [("2024-02-28", "2024-03-01", 2),
                                     ("2026-10-15", "2026-10-01", -14),
                                     ("2026-10-15", "2026-10-15", 0)]:
                result = await client.call_tool("date_difference", {"start_date": start, "end_date": end})
                self.assertEqual(result.data["days"], days)
            result = await client.call_tool("date_difference", {
                "start_date": "2026-02-30", "end_date": "2026-03-01"
            }, raise_on_error=False)
            self.assertTrue(result.is_error)

    async def test_text_statistics(self):
        async with Client(mcp) as client:
            result = await client.call_tool("text_statistics", {"text": "你好，MCP! Hello world"})
            self.assertEqual(result.data, {"characters": 19, "non_whitespace": 17,
                                          "chinese_characters": 2, "english_words": 3})
            result = await client.call_tool("text_statistics", {"text": ""})
            self.assertTrue(all(value == 0 for value in result.data.values()))

    async def test_original_dice_and_demo_news(self):
        async with Client(mcp) as client:
            result = await client.call_tool("roll_dice", {"n_dice": 100})
            self.assertEqual(len(result.data), 100)
            self.assertTrue(all(1 <= n <= 6 for n in result.data))
            result = await client.call_tool("get_news", {})
            self.assertIn("非实时新闻", result.data)


class AgentMCPIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_agent_calls_all_three_tools_over_sse(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        process = await asyncio.create_subprocess_exec(
            sys.executable, str(Path(__file__).with_name("homework2_server.py")), "--port", str(port),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            deadline = time.monotonic() + 30
            while True:
                try:
                    reader, writer = await asyncio.open_connection("127.0.0.1", port)
                    writer.close()
                    await writer.wait_closed()
                    break
                except OSError:
                    if process.returncode is not None or time.monotonic() > deadline:
                        self.fail("SSE 服务启动失败")
                    await asyncio.sleep(0.1)
            async with MCPServerSse(name="Week10Tools", params={"url": f"http://127.0.0.1:{port}/sse"}) as server:
                cases = [
                    ("calculate", {"a": "0.1", "operator": "+", "b": "0.2"}, "result", "0.3"),
                    ("date_difference", {"start_date": "2026-10-01", "end_date": "2026-10-15"}, "days", 14),
                    ("text_statistics", {"text": "你好，MCP! Hello world"}, "characters", 19),
                ]
                for name, args, field, expected in cases:
                    with self.subTest(tool=name):
                        call = {"role": "assistant", "content": None, "tool_calls": [{
                            "id": "call_test", "type": "function",
                            "function": {"name": name, "arguments": json.dumps(args)},
                        }]}
                        async with mock_model([call, answer("工具调用完成")]) as (model, requests):
                            run = await run_query(server, model, f"请调用 {name}")
                            self.assertEqual(run.final_output, "工具调用完成")
                            self.assertTrue(any(item.type == "tool_call_output_item" for item in run.new_items))
                            outputs = [m for m in requests[1]["messages"] if m["role"] == "tool"]
                            self.assertEqual(len(outputs), 1)
                            content = outputs[0]["content"]
                            payload = content if isinstance(content, str) else content[0]["text"]
                            self.assertEqual(json.loads(payload)[field], expected)
                            self.assertIn(name, {t["function"]["name"] for t in requests[0]["tools"]})
                            console = io.StringIO()
                            with redirect_stdout(console):
                                print_run(run)
                            self.assertIn(f"[调用工具] {name}", console.getvalue())
                            self.assertIn("[工具返回]", console.getvalue())
        finally:
            if process.returncode is None:
                process.terminate()
            await process.wait()


if __name__ == "__main__":
    unittest.main(verbosity=2)
