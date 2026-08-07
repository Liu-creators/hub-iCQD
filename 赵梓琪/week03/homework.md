# 作业一

1. langchain 工具调用 和 llm function call 有什么区别？

LangChain 是一个应用开发框架，它对工具注册、工具调用、Agent、Memory、Prompt、工作流等进行了统一封装，可以方便地构建复杂的 AI 应用。

LLM Function Calling 是大模型原生提供的工具调用能力，它负责根据用户输入判断是否需要调用工具，并按照预定义的 JSON Schema 返回工具名称和参数。开发者负责真正执行工具，并将执行结果再返回给模型。

两者不是替代关系，而是不同层次。Function Calling 属于底层模型能力，而 LangChain 属于上层框架。在实际开发中，LangChain 可以利用 OpenAI、Claude 等模型提供的 Function Calling 实现工具调用，但也支持 ReAct 等其他 Agent 实现方式，并不完全依赖 Function Calling。

2. langchain 工具调用 的 速度是受到什么影响？

大模型推理速度、工具执行本身需要的时间、Agent执行轮数、网络延迟、上下文长度

# 作业二

```mermaid
    flowchart TD
    A[客户端发送 POST 请求] --> B[FastAPI 路由]
    B --> C[解析 JSON 到 TextClassifyRequest]
    C --> D[创建 TextClassifyResponse 初始对象]
    D --> E[记录日志并开始计时]
    E --> F{选择接口}

    F -->|/v1/text-cls/regex| G[调用 model_for_regex]
    F -->|/v1/text-cls/tfidf| H[调用 model_for_tfidf]
    F -->|/v1/text-cls/bert| I[调用 model_for_bert]
    F -->|/v1/text-cls/gpt| J[调用 model_for_gpt]

    G --> K{执行成功？}
    H --> K
    I --> K
    J --> K

    K -->|是| L[填入 classify_result 和 error_msg=ok]
    K -->|否| M[捕获异常并写入 traceback 到 error_msg]

    L --> N[计算 classify_time]
    M --> N
    N --> O[返回 JSON 响应给客户端]
```