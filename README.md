# pro_planner

本地化企业项目策划与计划编制多智能体平台。当前进度是 **Phase 2**：文档解析、结构切分、embedding 入库、混合检索（全文 + 向量 + RRF + 可选 reranker）和可追溯引用。LangGraph 工作流、人工审核、导出和界面尚未实现。

规范来源：`/data/zch/workspace/EnterprisePlan_AI_Cursor_Project_Spec.md`。

## 当前环境

本机没有 Docker。应用和测试使用 conda 环境 `algo_infer`。数据库是已启用 pgvector 的 PostgreSQL 16，通过反向隧道访问本机 Docker（默认 `127.0.0.1:6001`，连接见本地 `.env`，不要提交）。隧道中断时集成测试无法连接数据库，单元测试仍可运行。

大模型推理单独用 `qwen3vl-sft` 启动 vLLM（当前为 0.29.0，支持 Qwen3.8）。不要把 vLLM 装进 `algo_infer`，避免和 FastAPI / LangGraph 依赖冲突。

```bash
# 终端 1：vLLM（占用 GPU 0）
bash /data/zch/workspace/pro_planner/scripts/start_vllm.sh

# 终端 2：应用
cd /data/zch/workspace/pro_planner
/data/djh/algo_infer/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```bash
cd /data/zch/workspace/pro_planner
/data/djh/algo_infer/bin/python -m pytest
```

最近一次：`45 passed`（`algo_infer`，Python 3.11，约 3.3s）。集成测试需要 `.env` 里的 PostgreSQL + pgvector 可用。RAG 集成测试强制 `embedding_provider=mock`，不加载 BGE、不调用 vLLM。

本机 CUDA 12.4 的 nvcc 无法编译 FlashInfer sampling（不支持 `--compress-mode`）。启动脚本已设置 `VLLM_USE_FLASHINFER_SAMPLER=0`。

`GET /health` 返回应用、数据库、pgvector、LLM/embedding 提供方，以及 `llm_ready`。响应不包含数据库连接串。`mock_mode=true` 时不得把结果当成真实模型输出。

## 模型

| 用途 | 本机配置 | 说明 |
| --- | --- | --- |
| LLM | `LLM_PROVIDER=openai_compatible`，`http://127.0.0.1:8001/v1`，`Qwen3.8-27B-FP8` | 权重在 `/data/zch/models/Qwen3.8-27B-FP8`，由 vLLM 提供 OpenAI 兼容接口 |
| Embedding | `EMBEDDING_PROVIDER=local`，`models/bge-m3` | 该目录是 `bge-large-zh-v1.5` 的符号链接，维度 1024，与 `vector(1024)` 一致。本机没有完整 `BAAI/bge-m3` |
| Reranker | 默认关闭；模型目录 `models/bge-reranker-v2-m3` | `RERANKER_ENABLED=true` 时用 sentence-transformers CrossEncoder，建议放 CPU 或空闲 GPU，避免和 vLLM 抢同一张卡 |

测试把 `LLM_PROVIDER` / `EMBEDDING_PROVIDER` 显式设为 `mock`，使用确定性向量，不下载、不调用大模型。配置会拒绝已知云端模型域名，也不会在本地服务失败时自动改连云 API。

本地 Hugging Face 权重目录不提交 git：

- `models/bge-reranker-v2-m3`
- `models/bge-m3` → `models/bge-large-zh-v1.5`

## Phase 2 能力

1. 上传 PDF / DOCX / XLSX 后调用 `POST /api/documents/{document_id}/index` 解析、切分、向量化并写入 `document_chunks`。
2. `POST /api/retrieval/search` 做混合检索：PostgreSQL `simple` 全文检索 + 中文/关键词 `ILIKE` 补充 + pgvector 余弦检索，再用 RRF 融合。
3. 返回 `EvidenceItem`：文档、版本、chunk、页码/章节、原文片段和核验状态。引用只表示用了该片段，不代表内容已获业务批准。

中文限制：`content_tsv` 使用 PostgreSQL `simple` 配置，不能当作中文分词已经解决。检索层会抽取汉字片段和二字窗口做关键词补充。

## API

已提供：

- `GET /health`
- `POST/GET /api/projects`，`GET /api/projects/{id}`
- `POST /api/documents/upload`，`GET /api/documents`
- `POST /api/documents/{document_id}/index`
- `POST /api/retrieval/search`

上传文件按 SHA-256 去重，存储名使用随机 UUID，数据库只保存相对路径。重复索引会替换该版本下的旧 chunk。

数据库迁移：

```bash
/data/djh/algo_infer/bin/alembic upgrade head
```

## 架构

```mermaid
flowchart LR
  upload[上传 PDF/DOCX/XLSX] --> parse[解析与结构切分]
  parse --> embed[Embedding]
  embed --> pg[(PostgreSQL + pgvector)]
  query[检索查询] --> lexical[全文 + 关键词]
  query --> vector[向量检索]
  lexical --> rrf[RRF]
  vector --> rrf
  rrf --> rerank[可选 Reranker]
  rerank --> evidence[EvidenceItem]
  vllm[vLLM Qwen3.8-27B-FP8] -.->|Phase 3 起用于生成| llm[LLM 网关]
```

## 尚未完成

Phase 3 起才会加入 LangGraph Checkpointer、各 Agent、人工审核、导出和 Streamlit 界面。Docker Compose 中的 `ui` 服务要等页面落地后才能运行。本机未安装 Docker，Compose 文件尚未在这里实际启动；容器网络里的模型服务仍按 `ollama` profile 预留。

## 隐私

不要上传未经授权的内部、涉密或个人敏感数据。日志不输出完整原文和密钥。
