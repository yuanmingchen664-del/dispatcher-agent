# 签派助手

签派知识库助手 MVP1。

第一阶段优先打通后端知识库闭环：

1. 上传手册和运行类文档。
2. 将原始文件保存到可配置的存储中。
3. 解析文档正文。
4. 将正文切分为可追溯的知识片段。
5. 生成 embedding。
6. 将知识片段写入 PostgreSQL + pgvector。
7. 根据检索结果回答问题，并返回引用来源。

本项目按中国大陆使用环境设计：不依赖海外 CDN，模型服务可配置，文件存储可使用本地目录、MinIO、阿里云 OSS、腾讯云 COS，或其他 S3 兼容对象存储。

## 技术栈

- FastAPI
- PostgreSQL + pgvector
- SQLAlchemy
- PyMuPDF，用于 PDF 解析
- OpenAI-compatible API 适配层，用于接入国内外 LLM 和 embedding 服务
- 本地或 S3 兼容对象存储

## 快速启动

```bash
cp .env.example .env
docker compose up -d db
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn backend.app.main:app --reload
```

打开 API 文档：

```text
http://127.0.0.1:8000/docs
```

运行检查：

```bash
python -m compileall backend tests
pytest
```

## MVP 接口

- `POST /documents/upload`
- `GET /documents`
- `GET /documents/{document_id}`
- `POST /documents/{document_id}/process`
- `POST /search`
- `POST /ask`
- `POST /feedback`

## 模型服务配置

本地冒烟测试可以使用：

```env
EMBEDDING_PROVIDER=mock
LLM_PROVIDER=mock
```

接入生产或准生产环境时，推荐使用 OpenAI-compatible 的国内模型服务。示例配置：

```env
EMBEDDING_PROVIDER=openai_compatible
EMBEDDING_BASE_URL=https://your-provider.example.com/v1
EMBEDDING_API_KEY=...
EMBEDDING_MODEL=...

LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://your-provider.example.com/v1
LLM_API_KEY=...
LLM_MODEL=...
```

后续可以接入 DeepSeek、通义千问、智谱、火山方舟等兼容接口，也可以替换为内网部署的模型服务。
# dispatcher-agent
