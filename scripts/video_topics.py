"""Video 论文的 arXiv 查询、类目边界与相关度规则。"""

from __future__ import annotations

import re
from typing import List, Sequence, Tuple


PRIMARY_QUERY = "ti:video"
FALLBACK_QUERY = "all:video"

ALLOWED_PRIMARY_CATEGORIES = {
    "cs.AI",
    "cs.CL",
    "cs.CV",
    "cs.LG",
    "cs.MM",
    "cs.RO",
}

TOPIC_PATTERNS: Sequence[Tuple[str, Sequence[str]]] = (
    (
        "视频生成",
        (
            "text-to-video",
            "image-to-video",
            "video generation",
            "video diffusion",
            "video synthesis",
            "generative video",
            "video world model",
        ),
    ),
    (
        "视频理解与推理",
        (
            "video understanding",
            "video reasoning",
            "video question answering",
            "video-language",
            "video language",
            "video llm",
            "video-language model",
            "multimodal video",
        ),
    ),
    (
        "视频编辑与控制",
        ("video editing", "video manipulation", "video inpainting", "video control"),
    ),
    (
        "视频分析与感知",
        (
            "video anomaly detection",
            "video segmentation",
            "video tracking",
            "action recognition",
            "temporal grounding",
            "video retrieval",
            "video captioning",
            "streaming video",
        ),
    ),
    (
        "视频数据与表征",
        (
            "video dataset",
            "video representation",
            "video pretraining",
            "video pre-training",
            "video encoder",
        ),
    ),
)


def classify_topics(title: str, abstract: str) -> List[str]:
    text = f"{title or ''} {abstract or ''}".lower()
    return [
        topic_name
        for topic_name, patterns in TOPIC_PATTERNS
        if any(pattern in text for pattern in patterns)
    ]


def relevance_score(title: str, abstract: str) -> int:
    title_lower = (title or "").lower()
    abstract_lower = (abstract or "").lower()
    combined_text = f"{title_lower} {abstract_lower}"
    score = 5 if re.search(r"\bvideos?\b", title_lower) else 0
    matched_patterns = sum(
        1
        for _, patterns in TOPIC_PATTERNS
        for pattern in patterns
        if pattern in combined_text
    )
    score += min(6, matched_patterns * 2)

    video_mentions = len(re.findall(r"\bvideos?\b", abstract_lower))
    if video_mentions >= 2:
        score += 1
    if video_mentions >= 5:
        score += 1
    return score


def is_relevant_video_paper(title: str, abstract: str) -> bool:
    if re.search(r"\bvideos?\b", (title or "").lower()):
        return True
    # The fallback query already requires ``video`` somewhere in the paper.
    # Accept one strong video-topic phrase plus repeated video evidence so that
    # clearly relevant papers whose titles omit "video" can fill the daily ten.
    return relevance_score(title, abstract) >= 3
