import base64
from typing import Any, Optional, Protocol

from openai import OpenAI

from backend.app.core.config import Settings


class OCRProvider(Protocol):
    def recognize_png(self, image_bytes: bytes) -> str:
        ...


class OpenAICompatibleVisionOCRProvider:
    def __init__(self, settings: Settings):
        api_key = settings.ocr_api_key or settings.llm_api_key
        base_url = settings.ocr_base_url or settings.llm_base_url
        if not api_key:
            raise RuntimeError("启用远程 OCR 时需要配置 OCR_API_KEY 或 LLM_API_KEY")
        if not base_url:
            raise RuntimeError("启用远程 OCR 时需要配置 OCR_BASE_URL 或 LLM_BASE_URL")
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = settings.ocr_model
        self.prompt = settings.ocr_prompt

    def recognize_png(self, image_bytes: bytes) -> str:
        image_data = base64.b64encode(image_bytes).decode("ascii")
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": self.prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{image_data}"},
                        },
                    ],
                }
            ],
            temperature=0,
        )
        return (response.choices[0].message.content or "").strip()


def extract_ocr_text(result: Any) -> str:
    texts: list[str] = []
    _collect_ocr_text(result, texts)
    return "\n".join(text for text in texts if text).strip()


def _collect_ocr_text(value: Any, texts: list[str]) -> None:
    if value is None:
        return

    if isinstance(value, dict):
        if "rec_texts" in value and isinstance(value["rec_texts"], list):
            texts.extend(str(item) for item in value["rec_texts"] if item)
        elif "text" in value and value["text"]:
            texts.append(str(value["text"]))
        elif "transcription" in value and value["transcription"]:
            texts.append(str(value["transcription"]))
        for item in value.values():
            _collect_ocr_text(item, texts)
        return

    json_value = getattr(value, "json", None)
    if isinstance(json_value, dict):
        _collect_ocr_text(json_value, texts)
        return

    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        _collect_ocr_text(to_dict(), texts)
        return

    if isinstance(value, (list, tuple)):
        if len(value) >= 2 and isinstance(value[1], (list, tuple)) and value[1]:
            candidate = value[1][0]
            if isinstance(candidate, str):
                texts.append(candidate)
                return
        for item in value:
            _collect_ocr_text(item, texts)


def get_ocr_provider(settings: Settings) -> Optional[OCRProvider]:
    if settings.ocr_provider == "openai_compatible_vision":
        return OpenAICompatibleVisionOCRProvider(settings)
    return None
