***
作业1:
1、langchain 工具调用 和 llm function call 有什么区别？
function call是底层协议，大模型自带的原生能力
Langchain对 function call进行了封装与增强
2、langchain 工具调用 的 速度是受到什么影响？
速度主要受到了网络延迟与模型推理时间，还有工具间的互相调用


作业2:
请求流向：
客户端
  ↓
main.py （路由分发 + 响应组装）
  ↓
data_schema.py （数据验证） ←── 独立模块
config.py （配置加载） 
  ↓                                                
model/regex_rule.py ──→ 读取 config.REGEX_RULE       
model/tfidf_ml.py  ──→ 读取 config.TFIDF_MODEL_PATH 
model/bert.py        ──→ 读取 config.BERT_* 配置    
model/prompt.py      ──→ 读取 config.LLM_* 配置     
  ↓                                                
logger.py （日志记录） ←── 独立模块                    
  ↓                                                
返回客户端 
***
