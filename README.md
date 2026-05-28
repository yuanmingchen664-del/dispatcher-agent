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

## 测试资料

仓库内提供了一份不含真实运行资料的测试文档：

```text
test_assets/签派助手测试手册.txt
```

它用于验证：

- 文档上传
- 文本解析
- 知识片段切分
- embedding 入库
- 检索和问答接口

当前第一轮建议优先使用 TXT 测试完整闭环。中文 PDF 需要进一步处理字体嵌入、扫描件 OCR、表格解析等问题，后续会单独增强。

## 知识片段切分

当前切分策略优先识别：

- 中文章节标题，例如 `第一章 目的地天气放行标准`
- 英文章节标题，例如 `Chapter 1 ...`
- 条款编号，例如 `1.1`、`2.3`

系统会尽量按章节组织 chunk，并在元数据中记录：

- `chapter`：章节标题
- `articles`：chunk 内包含的条款编号
- `char_count`：字符数

修改切分策略后，需要重新处理文档，旧 chunk 才会被替换：

```text
POST /documents/{document_id}/process
```

查看某份文档已经生成的 chunk：

```text
GET /documents/{document_id}/chunks
```

这个接口用于检查 PDF 或 TXT 被系统解析后的真实效果，不会调用模型，也不会消耗模型 API 额度。

## MVP 接口

- `POST /documents/upload`
- `GET /documents`
- `GET /documents/{document_id}`
- `GET /documents/{document_id}/chunks`
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

硅基流动接入说明见：

```text
docs/siliconflow.md
```
# dispatcher-agent
