import hashlib
from typing import Protocol

from openai import OpenAI

from backend.app.core.config import Settings
from backend.app.schemas import SourceOut


class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]:
        ...


class LLMProvider(Protocol):
    def answer(self, question: str, sources: list[SourceOut]) -> str:
        ...


class MockEmbeddingProvider:
    def __init__(self, dimensions: int):
        self.dimensions = dimensions

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        values = []
        for index in range(self.dimensions):
            byte = digest[index % len(digest)]
            values.append((byte / 255.0) - 0.5)
        return values


class OpenAICompatibleEmbeddingProvider:
    def __init__(self, settings: Settings):
        self.client = OpenAI(api_key=settings.embedding_api_key, base_url=settings.embedding_base_url)
        self.model = settings.embedding_model

    def embed(self, texts: list[str]) -> list[list[float]]:
        response = self.client.embeddings.create(model=self.model, input=texts)
        return [item.embedding for item in response.data]


class MockLLMProvider:
    def answer(self, question: str, sources: list[SourceOut]) -> str:
        if not sources:
            return "未在当前知识库中检索到足够依据。请补充手册或调整问题。"
        source_lines = "\n".join(
            f"- {source.document_title} p.{source.page_start or '-'}: {source.content[:120]}"
            for source in sources
        )
        return (
            "这是本地 mock 回答，用于验证 MVP 闭环。\n\n"
            f"问题：{question}\n\n"
            "建议：请结合以下检索依据由正式模型生成最终签派建议；涉及放行决策时必须人工复核。\n\n"
            f"依据：\n{source_lines}"
        )


class OpenAICompatibleLLMProvider:
    def __init__(self, settings: Settings):
        self.client = OpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url)
        self.model = settings.llm_model

    def answer(self, question: str, sources: list[SourceOut]) -> str:
        context = "\n\n".join(
            (
                f"[{index}] {source.document_title}"
                f" chapter={source.chapter or '-'} pages={source.page_start or '-'}-{source.page_end or '-'}\n"
                f"{source.content}"
            )
            for index, source in enumerate(sources, start=1)
        )
        system = (
            "你是航空签派知识库助手。只能基于提供的手册片段回答。"
            "回答必须包含：结论、依据、判断步骤、风险提示、需要补充的信息。"
            "如果依据不足，明确说明不能下结论。"
        )
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": f"问题：{question}\n\n手册片段：\n{context}"},
            ],
            temperature=0.2,
        )
        return response.choices[0].message.content or ""


def get_embedding_provider(settings: Settings) -> EmbeddingProvider:
    if settings.embedding_provider == "openai_compatible":
        return OpenAICompatibleEmbeddingProvider(settings)
    return MockEmbeddingProvider(settings.embedding_dimensions)


def get_llm_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "openai_compatible":
        return OpenAICompatibleLLMProvider(settings)
    return MockLLMProvider()

