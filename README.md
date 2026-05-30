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
- React + Vite + TypeScript
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

启动前端：

```bash
cd frontend
npm install
npm run dev
```

打开前端：

```text
http://127.0.0.1:5173
```

运行检查：

```bash
python -m compileall backend tests
pytest
cd frontend && npm run build
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

## PDF OCR

当前 PDF 解析采用混合策略：

- 优先使用 PyMuPDF 读取 PDF 文本层
- 如果某页提取到的文字少于 `OCR_MIN_TEXT_CHARS`，并且启用了 OCR，则将该页渲染为图片
- 图片通过硅基流动 OpenAI-compatible 视觉接口交给 OCR 模型识别
- OCR 结果继续进入 chunk 切分和 embedding 流程

`.env` 配置：

```env
OCR_PROVIDER=openai_compatible_vision
OCR_MIN_TEXT_CHARS=30
OCR_DPI=200
OCR_BASE_URL=https://api.siliconflow.cn/v1
OCR_API_KEY=你的硅基流动_API_Key
OCR_MODEL=PaddlePaddle/PaddleOCR-VL-1.5
```

如果不需要 OCR：

```env
OCR_PROVIDER=none
```

如果不单独配置 `OCR_BASE_URL` 和 `OCR_API_KEY`，系统会复用 `LLM_BASE_URL` 和 `LLM_API_KEY`。
启用远程 OCR 后，扫描页图片会发送到硅基流动 OCR 模型。

## 知识片段切分

当前切分策略优先识别：

- 中文章节标题，例如 `第一章 目的地天气放行标准`
- 英文章节标题，例如 `Chapter 1 ...`
- 条款编号，例如 `1.1`、`2.3`

系统会尽量按章节组织 chunk，并在元数据中记录：

- `chapter`：章节标题
- `articles`：chunk 内包含的条款编号
- `page_start` / `page_end`：chunk 覆盖的 PDF 页码范围
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

按条款号查看 chunk：

```text
GET /documents/{document_id}/chunks?article=121.637
```

查看文档大纲和章节数量：

```text
GET /documents/{document_id}/outline
```

这类接口适合回答“整份文档一共有多少章、有哪些附件”这样的全局统计问题。普通 RAG 检索更适合回答具体条款问题。

`POST /ask` 已内置轻量路由：如果问题明显是在问“多少章、章节、目录、附件、附录、大纲”，系统会优先走文档大纲逻辑，而不是普通向量检索。

## 统一证据来源

`POST /ask` 和 `POST /search` 返回的每个来源都会包含 `evidence` 字段，前端可以直接渲染成证据卡片。

规章或手册类来源通常包含：

- `source_type`：例如 `regulation`、`manual`、`ops_spec`
- `label`：例如 `CCAR121 / U 章 签派和飞行放行 / 第121.637条 / 第243页`
- `article`：条款号
- `page_label`：页码
- `reliability`：例如 `official`、`company`

经验记录、案例复盘或处置模板可以不包含条款号，建议上传时填写：

- `source_type=experience`
- `scenario=低能见度放行`
- `author=签派员A`
- `department=AOC`
- `reliability=experiential`

经验类来源的 `label` 类似：`低能见度放行复盘 / 低能见度放行 / 2026-05-28 / 签派员A`。

## 直接录入经验记录

个人经验可以通过 `POST /notes` 直接写入知识库，不需要先做成文件：

```bash
curl -X POST http://127.0.0.1:8000/notes \
  -H "Content-Type: application/json" \
  -d '{
    "title": "低能见度放行复盘",
    "content": "目的地 RVR 波动较大时，我会先检查趋势报、备降机场天气和额外油量，再结合公司运行标准判断是否继续放行。",
    "scenario": "低能见度放行",
    "source_type": "experience",
    "author": "我",
    "effective_date": "2026-05-29",
    "reliability": "experiential"
  }'
```

该接口会自动创建文档记录、切分 chunk、生成 embedding。后续 `/ask` 会同时检索手册、规章和个人经验。

如果希望在 agent 窗口里直接输入，可以使用统一入口 `POST /agent/message`：

```bash
curl -X POST http://127.0.0.1:8000/agent/message \
  -H "Content-Type: application/json" \
  -d '{
    "message": "记一下 关于低能见度放行：目的地 RVR 波动较大时，我会先检查趋势报、备降机场天气和额外油量。",
    "author": "我",
    "effective_date": "2026-05-29"
  }'
```

当输入以 `记一下`、`记录一下`、`保存经验`、`帮我记住` 等开头时，系统会自动分析为个人经验并入库；否则会按普通问题走知识库问答。

## MVP 接口

- `POST /documents/upload`
- `POST /notes`
- `POST /agent/message`
- `GET /documents`
- `GET /documents/{document_id}`
- `GET /documents/{document_id}/chunks`
- `GET /documents/{document_id}/outline`
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
EMBEDDING_BATCH_SIZE=64

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
