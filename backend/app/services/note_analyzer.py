from dataclasses import dataclass
import re
from typing import Optional


NOTE_INTENT_PREFIXES = [
    "记一下",
    "记录一下",
    "保存经验",
    "存一下",
    "帮我记住",
    "加入经验",
    "写入经验",
]


@dataclass
class AnalyzedNote:
    title: str
    content: str
    scenario: Optional[str]
    source_type: str = "experience"
    reliability: str = "experiential"


def analyze_note_message(message: str) -> Optional[AnalyzedNote]:
    cleaned = message.strip()
    if not cleaned:
        return None

    content = strip_note_prefix(cleaned)
    if content is None:
        return None

    scenario, content = extract_scenario(content)
    content = cleanup_note_content(content)
    if not content:
        return None

    title = build_note_title(content, scenario)
    return AnalyzedNote(title=title, content=content, scenario=scenario)


def strip_note_prefix(message: str) -> Optional[str]:
    normalized = message.strip()
    for prefix in NOTE_INTENT_PREFIXES:
        if normalized.startswith(prefix):
            return normalized[len(prefix) :].strip(" ：:，,。")

    match = re.match(r"^(?:经验|案例|复盘|模板)\s*[：:](.+)$", normalized, flags=re.DOTALL)
    if match:
        return match.group(1).strip()
    return None


def extract_scenario(content: str) -> tuple[Optional[str], str]:
    patterns = [
        r"^场景\s*[：:]\s*(.+?)[；;。.\n]\s*(.+)$",
        r"^关于\s*(.+?)\s*(?:的)?(?:经验|复盘|案例|处置)?[：:，,]\s*(.+)$",
        r"^(.+?)(?:场景|情况下)[：:，,]\s*(.+)$",
    ]
    for pattern in patterns:
        match = re.match(pattern, content.strip(), flags=re.DOTALL)
        if match:
            scenario = cleanup_scenario(match.group(1))
            remaining = cleanup_note_content(match.group(2))
            return scenario, remaining
    return infer_scenario(content), content


def infer_scenario(content: str) -> Optional[str]:
    candidates = [
        "低能见度",
        "起飞备降",
        "目的地备降",
        "备降机场",
        "雷雨绕飞",
        "油量",
        "MEL",
        "航路天气",
        "大风",
        "除冰",
    ]
    for candidate in candidates:
        if candidate in content:
            return candidate
    return None


def build_note_title(content: str, scenario: Optional[str]) -> str:
    if scenario:
        return f"{scenario}经验记录"
    first_sentence = re.split(r"[。！？!?\n]", content.strip(), maxsplit=1)[0]
    title = first_sentence[:24].strip(" ：:，,。")
    return title or "经验记录"


def cleanup_scenario(value: str) -> str:
    return value.strip(" ：:，,。的")


def cleanup_note_content(value: str) -> str:
    return value.strip(" \n\t：:，,。")
