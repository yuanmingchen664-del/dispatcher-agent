# 接入硅基流动

硅基流动支持 OpenAI-compatible API，本项目可以直接通过 `.env` 接入。

## 1. 获取 API Key

登录硅基流动控制台，进入 API 密钥页面，新建并复制 API Key。

```text
https://cloud.siliconflow.cn/account/ak
```

API Key 通常以 `sk-` 开头。不要提交到 Git。

## 2. 选择模型

进入模型广场，复制完整模型名称。

```text
https://cloud.siliconflow.cn/models
```

示例：

```text
deepseek-ai/DeepSeek-V3
BAAI/bge-m3
```

模型名称可能会调整，请以硅基流动模型广场当前展示为准。

## 3. 修改 .env

推荐先用 `BAAI/bge-m3` 做 embedding。该模型常用向量维度为 `1024`，因此需要同步设置：

```env
EMBEDDING_PROVIDER=openai_compatible
EMBEDDING_BASE_URL=https://api.siliconflow.cn/v1
EMBEDDING_API_KEY=你的硅基流动_API_Key
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_DIMENSIONS=1024

LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://api.siliconflow.cn/v1
LLM_API_KEY=你的硅基流动_API_Key
LLM_MODEL=deepseek-ai/DeepSeek-V3
```

## 4. 重建测试数据库

如果之前已经用 `mock` embedding 建过表，数据库里的向量维度是 `384`。切换到 `1024` 维 embedding 后，测试阶段最简单的做法是清空并重建数据库：

```bash
docker compose down -v
docker compose up -d db
```

这会删除当前测试数据。正式环境以后要用数据库迁移，不直接删库。

## 5. 重启后端

```bash
source .venv/bin/activate
uvicorn backend.app.main:app --reload
```

## 6. 重新处理文档

换成真实 embedding 后，之前用 mock 生成的向量不能继续用。需要重新上传或重新处理文档：

```text
POST /documents/upload
POST /documents/{document_id}/process
POST /ask
```

