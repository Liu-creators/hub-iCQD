# 意图识别技术与实战

基于中文语音助手场景的**意图识别（文本分类）**完整项目：从数据、四路模型到 API 服务、评测报告全链路。

> 场景：智能座舱 / 智能家居语音助手。用户说一句话，系统判断其意图（播放音乐？查天气？设闹钟？…），是 NLU 的第一环。

## 项目结构

```
pj1/
├── README.md                        # 项目说明（本文件）
├── .env.example                     # LLM API key 配置模板（复制为 .env 后填写）
├── .gitignore                       # 忽略大文件（模型权重/.env）
│
├── assets/                          # 数据与模型资产
│   ├── dataset/
│   │   ├── dataset.csv              # 原始数据：12,073 条 / 12 类意图（文本\t意图）
│   │   ├── baidu_stopwords.txt      # 停用词表（TF-IDF 路线使用）
│   │   └── split/                   # 分层划分结果
│   │       ├── train.csv            # 训练集 9,655 条（80%）
│   │       ├── val.csv              # 验证集 1,202 条（10%）
│   │       └── test.csv             # 测试集 1,216 条（10%）
│   ├── models/
│   │   └── bert-base-chinese/       # BERT 预训练模型（本地加载，免下载）
│   │       ├── config.json          # 模型配置
│   │       ├── pytorch_model.bin    # 预训练权重（~393MB）
│   │       ├── vocab.txt            # 词表
│   │       ├── tokenizer.json       # tokenizer
│   │       └── tokenizer_config.json
│   └── weights/                     # 训练产物（git 忽略，需自行训练生成）
│       ├── bert_intent.pt           # BERT 微调权重（~400MB）
│       └── tfidf_svm.pkl            # TF-IDF+SVM 管线（joblib）
│
├── src/                             # 源代码
│   ├── config.py                    # 全局配置：路径/12类意图/正则规则/超参数/LLM接口
│   ├── data_process.py              # 数据加载、分层划分、分布可视化
│   ├── model_regex.py               # 路线1：正则规则匹配（零训练基线）
│   ├── model_tfidf.py               # 路线2：TF-IDF + SVM/LR（传统ML基线）
│   ├── model_bert.py                # 路线3：BERT 微调（主力模型，训练+推理）
│   ├── model_llm.py                 # 路线4：DeepSeek + TF-IDF 动态 few-shot
│   ├── evaluate.py                  # 统一评测：准确率/F1/延迟/混淆矩阵/错误分析
│   └── api.py                       # FastAPI 服务：4 个 RESTful 接口 + Swagger
│
├── scripts/                         # 一键运行脚本
│   ├── prepare_data.py              # ① 数据准备（划分+可视化）
│   ├── train_tfidf.py               # ② 训练 TF-IDF+SVM 基线
│   ├── train_bert.py                # ③ 微调 BERT（--force 强制重训）
│   └── run_eval.py                  # ④ 全模型统一评测
│
├── docs/                            # 项目文档
│   ├── 01_项目背景.md                # 应用场景/痛点/目标/产出
│   ├── 02_项目实施.md                # 技术选型/实施步骤/问题与解决方案
│   ├── 03_项目运维.md                # 部署/API调用/性能监控
│   ├── 04_项目面试点.md              # 面试高频追问与回答
│   ├── 05_项目成果报告.md            # 真实评测结果（对比表/F1/错误分析）
│   └── 06_简历项目描述.md            # 简历用项目描述（背景→目标→难点→成果）
│
└── output/                          # 评测产物（自动生成）
    ├── eval_report.json             # 四路模型评测数据（机器可读）
    ├── llm_eval_subset.csv          # LLM 路线 300 条子集评测明细
    ├── confusion_matrix_bert.png    # BERT 混淆矩阵热力图
    ├── data_distribution.png        # 类别分布图
    ├── text_len_distribution.png    # 文本长度分布图
    └── bert_training_history.json   # BERT 训练历史（loss/val_acc）
```

## 快速开始

```bash
# 1. 配置 API key（LLM 路线需要）
cp .env.example .env   # 填入 DEEPSEEK_API_KEY

# 2. 数据准备（划分 + 可视化）
python scripts/prepare_data.py

# 3. 训练（注意：在 Windows 下若 PYTHONPATH 被污染先执行 export PYTHONPATH=）
python scripts/train_tfidf.py     # 基线，秒级
python scripts/train_bert.py      # 主力，RTX 4060 约 3 分钟/4 epochs

# 4. 评测
python scripts/run_eval.py

# 5. 启动 API 服务
cd src && uvicorn api:app --host 0.0.0.0 --port 8000
# Swagger 文档: http://localhost:8000/docs
```

## 四路技术路线

| 路线 | 方法 | 训练 | 延迟 | 特点 |
|---|---|---|---|---|
| 1 | 正则规则匹配 | 无 | 亚毫秒 | 规则强、意图明确的指令，冷启动兜底 |
| 2 | TF-IDF + SVM | 有（秒级） | 毫秒级 | 传统 ML，可解释，资源占用小 |
| 3 | **BERT 微调** | 有（GPU 分钟级） | ~10ms | **主力模型**，精度最高 |
| 4 | DeepSeek + 动态 few-shot | 无（提示词工程） | 百毫秒级 | 零训练，长尾/新说法泛化好，成本随调用量 |

## 评测结果（真实运行）

详见 [`docs/05_项目成果报告.md`](docs/05_项目成果报告.md) 与 `output/eval_report.json`。

## 环境

- Python 3.12（conda env: `study`），PyTorch 2.13 + CUDA，transformers 4.56
- RTX 4060 Laptop 8GB
