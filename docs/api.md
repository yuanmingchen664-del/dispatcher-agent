# MVP1 API 流程

## 1. 上传手册

```bash
curl -X POST http://127.0.0.1:8000/documents/upload \
  -F "file=@manual.pdf" \
  -F "title=A320 FOM" \
  -F "doc_type=FOM" \
  -F "version=Rev.1"
```

## 2. 处理手册

```bash
curl -X POST http://127.0.0.1:8000/documents/{document_id}/process
```

处理流程包括：

- 从存储下载原始文件
- 提取正文
- 切分知识片段
- 生成 embedding
- 持久化知识片段

## 3. 检索

处理完成后，可以先查看文档 chunk：

```bash
curl http://127.0.0.1:8000/documents/{document_id}/chunks
```

这个接口会返回每个 chunk 的正文、章节、页码和元数据，适合检查 PDF 解析质量。

```bash
curl -X POST http://127.0.0.1:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query":"目的地天气低于标准是否可以放行？"}'
```

## 4. 问答

```bash
curl -X POST http://127.0.0.1:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"目的地天气低于标准是否可以放行？"}'
```

返回内容包括：

- 答案
- 引用的知识片段
- 文档元数据
- 问答日志 id
