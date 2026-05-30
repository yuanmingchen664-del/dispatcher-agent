# MVP1 API 流程

## 1. 上传手册

```bash
curl -X POST http://127.0.0.1:8000/documents/upload \
  -F "file=@manual.pdf" \
  -F "title=A320 FOM" \
  -F "doc_type=FOM" \
  -F "version=Rev.1"
```

经验记录也走同一个上传接口，只是需要补充来源元数据：

```bash
curl -X POST http://127.0.0.1:8000/documents/upload \
  -F "file=@experience.md" \
  -F "title=低能见度放行复盘" \
  -F "source_type=experience" \
  -F "scenario=低能见度放行" \
  -F "author=签派员A" \
  -F "department=AOC" \
  -F "reliability=experiential" \
  -F "effective_date=2026-05-28"
```

## 2. 处理手册

```bash
curl -X POST http://127.0.0.1:8000/documents/{document_id}/process
```

处理流程包括：

- 从存储下载原始文件
- 提取正文
- 如果启用 OCR，扫描型 PDF 页面会通过远程 OCR 模型识别
- 切分知识片段
- 生成 embedding
- 持久化知识片段

## 3. 直接录入经验记录

个人经验可以不做成文件，直接写入知识库：

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

该接口会直接创建文档记录、切分 chunk、生成 embedding，并进入后续 `/ask` 检索范围。

也可以走 agent 窗口统一入口，让后端自动判断是“保存经验”还是“普通提问”：

```bash
curl -X POST http://127.0.0.1:8000/agent/message \
  -H "Content-Type: application/json" \
  -d '{
    "message": "记一下 关于低能见度放行：目的地 RVR 波动较大时，我会先检查趋势报、备降机场天气和额外油量。",
    "author": "我",
    "effective_date": "2026-05-29"
  }'
```

如果 `message` 不是“记一下、保存经验、帮我记住”等记录意图，这个接口会自动转为普通 `/ask` 问答。

## 4. 检索

处理完成后，可以先查看文档 chunk：

```bash
curl http://127.0.0.1:8000/documents/{document_id}/chunks
```

这个接口会返回每个 chunk 的正文、章节、页码和元数据，适合检查 PDF 解析质量。

也可以按条款号过滤，例如只查看第 121.637 条相关片段：

```bash
curl "http://127.0.0.1:8000/documents/{document_id}/chunks?article=121.637"
```

查看文档大纲：

```bash
curl http://127.0.0.1:8000/documents/{document_id}/outline
```

大纲接口适合统计整份文档的章节数量和附件数量。

```bash
curl -X POST http://127.0.0.1:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query":"目的地天气低于标准是否可以放行？"}'
```

## 5. 问答

```bash
curl -X POST http://127.0.0.1:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"目的地天气低于标准是否可以放行？"}'
```

返回内容包括：

- 答案
- 引用的知识片段
- 统一证据卡片 `evidence`
- 文档元数据
- 问答日志 id
