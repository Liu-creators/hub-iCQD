import json
import os
from pathlib import Path

from agents import set_default_openai_api, set_default_openai_client, set_tracing_disabled
from openai import AsyncOpenAI

# 新版 openai SDK(>=3)用 httpx2，旧版用 httpx，这里做兼容
try:
    from openai import DefaultAsyncHttpx2Client as DefaultAsyncHttpClient
except ImportError:
    from openai import DefaultAsyncHttpxClient as DefaultAsyncHttpClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]


async def log_request(request):
    print("\n=== HTTP REQUEST ===")
    print(request.method, request.url)
    # 只打印 body，不打印 headers，避免泄露 Authorization
    body = request.content.decode("utf-8")
    try:
        print(json.dumps(json.loads(body), ensure_ascii=False, indent=2))
    except json.JSONDecodeError:
        print(body)


async def log_response(response):
    await response.aread()  # response hook 触发时 body 还没读，需要先读
    print("\n=== HTTP RESPONSE ===")
    print("status:", response.status_code)
    try:
        print(json.dumps(response.json(), ensure_ascii=False, indent=2))
    except Exception:
        print(response.text)


def load_project_env() -> None:
    """读取项目根目录的 .env。已存在的环境变量优先。"""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def env_value(name: str) -> str:
    """只从环境变量读取。调用前会把项目 .env 载入环境变量。"""
    load_project_env()
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"缺少环境变量 {name}")
    return value


def model_name() -> str:
    return env_value("MODEL_NAME")


def base_url() -> str:
    return env_value("BASE_URL")


def _http_log_enabled() -> bool:
    return os.environ.get("TRANSLATOR_HTTP_LOG", "").strip().lower() in {"1", "true", "yes"}


def setup_client() -> None:
    """配置 DashScope 客户端。导入本模块不会读取密钥。"""
    api_key = env_value("DASHSCOPE_API_KEY")

    client_kwargs = {}
    if _http_log_enabled():
        client_kwargs["event_hooks"] = {"request": [log_request], "response": [log_response]}
    http_client = DefaultAsyncHttpClient(**client_kwargs)
    client = AsyncOpenAI(api_key=api_key, base_url=base_url(), http_client=http_client)
    set_default_openai_client(client, use_for_tracing=False)
    set_default_openai_api("chat_completions")
    set_tracing_disabled(True)
