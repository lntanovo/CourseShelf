"""Explainable, local filename suggestions. Never performs a file operation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path


def _normal(value: str) -> str:
    return re.sub(r"[\s._\-（）()【】\[\]·]+", "", value).casefold()


@dataclass(frozen=True)
class Suggestion:
    course: str | None
    category: str | None
    reason: str
    confidence: str = "high"


KEYWORDS = {
    "课件": ("课件", "ppt", "讲义"),
    "作业": ("作业", "homework"),
    "复习资料": ("复习", "考试", "真题"),
}


def suggest(filename: str, courses: list[str], categories: list[str] | None = None,
            aliases: dict[str, list[str]] | None = None) -> Suggestion:
    stem = _normal(Path(filename).stem)
    confidence = "high"
    matches = [course for course in courses if _normal(course) and _normal(course) in stem]
    if matches:
        longest = max(len(_normal(course)) for course in matches)
        longest_matches = [course for course in matches if len(_normal(course)) == longest]
        course = longest_matches[0] if len(longest_matches) == 1 else None
        reason = f"文件名包含课程全名“{course}”" if course else "文件名命中多个同长度课程，需手动选择"
    else:
        course = None
        reason = "文件名未唯一命中课程，需手动选择"
        hits = [name for name in courses if any(_normal(alias) and _normal(alias) in stem for alias in (aliases or {}).get(name, []))]
        if len(set(hits)) == 1:
            course = hits[0]
            reason = f"文件名命中用户设置的课程别名“{course}”"
        elif hits:
            reason = "同一别名命中多个课程，需手动选择"
        else:
            fragments = [_normal(part) for part in re.split(r"[\s._\-（）()【】\[\]]+", Path(filename).stem)]
            scores = sorted(((max((SequenceMatcher(None, _normal(name), part).ratio() for part in fragments if len(part) >= 3), default=0), name)
                             for name in courses), reverse=True)
            if scores and scores[0][0] >= 0.8:
                if len(scores) == 1 or scores[0][0] - scores[1][0] >= 0.12:
                    course = scores[0][1]
                    confidence = "low"
                    reason = f"低置信模糊建议“{course}”，需手动选择后才能归档"
                else:
                    reason = "多个近似课程，需手动选择"
    available = set(categories or [])
    category_hits = [name for name, words in KEYWORDS.items()
                     if name in available and any(_normal(word) in stem for word in words)]
    if len(category_hits) == 1:
        category = category_hits[0]
        reason += f"；文件名关键词建议“{category}”"
    elif len(category_hits) > 1:
        category = None
        reason += "；命中多个分类关键词，需手动选择"
    elif "其他" in available:
        category = "其他"
        reason += "；无分类关键词，默认建议“其他”"
    else:
        category = None
        reason += "；无可用分类建议，需手动选择"
    return Suggestion(course, category, reason, confidence if course else "none")
