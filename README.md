# pro_planner

本地化企业项目策划与计划编制多智能体平台。当前进度是 **Phase 1**：配置、健康检查、业务表迁移、项目接口和文档上传登记。RAG、工作流、导出和界面尚未实现。

规范来源：`/data/zch/workspace/EnterprisePlan_AI_Cursor_Project_Spec.md`。

## 当前环境

本机没有 Docker。开发和测试使用 conda 环境 `algo_infer`，数据库是已启用 pgvector 的 PostgreSQL 16（连接见本地 `.env`，不要提交）。

```bash
cd /data/zch/workspace/pro_planner
/data/djh/algo_infer/bin/python -m pytest
```

健康检查：

```bash
/data/djh/algo_infer/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

`GET /health` 返回应用、数据库和 pgvector 状态，并标明当前是否处于 Mock 模式。响应不包含数据库连接串。

## 模型

默认 `LLM_PROVIDER=ollama`，地址指向本机服务。测试把 `LLM_PROVIDER` 和 `EMBEDDING_PROVIDER` 设为 `mock`。配置会拒绝已知云端模型域名，也不会在本地服务失败时自动改连云 API。

Docker Compose 里的 `ollama` 服务使用 `models` profile，启动时不会下载模型权重。`ui` 服务要等 Streamlit 页面落地后才能运行。

数据库迁移：

```bash
/data/djh/algo_infer/bin/alembic upgrade head
```

已提供 `GET /health`、`POST/GET /api/projects`、`GET /api/projects/{id}`、`POST /api/documents/upload`、`GET /api/documents`。上传文件按 SHA-256 去重，存储名使用随机 UUID，数据库只保存相对路径。

`document_chunks.embedding` 固定为 `vector(1024)`。`content_tsv` 使用 PostgreSQL `simple` 配置，不能当作中文分词已经解决。

## 尚未完成

Phase 2 起才会加入文档解析、混合检索、LangGraph Checkpointer、人工审核、导出和界面。Docker Compose 中的 `ui` 服务要等 Streamlit 页面落地后才能运行。本机未安装 Docker，Compose 文件尚未在这里实际启动。
