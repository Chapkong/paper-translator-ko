#!/usr/bin/env python3
"""추출 품질 채점. 기준 미달이면 번역을 시작하지 않는다.

깨진 원문을 번역하면 토큰만 쓰고 결과도 못 쓴다. 여기서 막는 것이 가장 싸다.
"""
import re
from dataclasses import dataclass

MIN_COVERAGE = 0.97   # 문자 보존율 하한
MAX_TRUNCATED = 0.05  # 잘린 문단 비율 상한
                      # Peteraf 회귀로 조정한 값이다. 정상 추출 0.037,
                      # 좌우 단이 섞인 추출 0.145, 기존 경로 0.903 — 사이가 충분히 벌어진다.

_STRIP = re.compile(r"[\s­\-]")
_ENDINGS = tuple(".!?\"')]”’」』")


@dataclass
class Score:
    coverage: float
    truncated: float
    ok: bool


def norm_len(t: str) -> int:
    """공백·하이픈을 뺀 문자 수. 줄바꿈 처리 차이가 점수에 영향을 주지 않게 한다."""
    return len(_STRIP.sub("", t))


# 원래 문장부호로 끝나지 않는 문단들 — 손상이 아니므로 세지 않는다
_SKIP_PARA = re.compile(
    r"^(figure|table|fig\.|source:|author\(s\):|published by:|stable url:|key:|그림|표\s)", re.I)
_REFS = re.compile(r"^#*\s*(references|참고문헌|bibliography)\s*$", re.I | re.M)


def _ends_properly(p: str) -> bool:
    """문장이 제대로 끝났는가. 마침표 뒤에 붙은 각주 표시 번호는 무시한다
    (`…(Rumelt, 1987). 13`, `…firm-specific needs.16`)."""
    return re.sub(r"(?<=[.!?])\s?\d{1,3}$", "", p.rstrip()).endswith(_ENDINGS)


def checked_paragraphs(md: str) -> list:
    """절단 검사 대상 문단.

    빼는 것들 — 손상이 아니라 원래 그런 것이다:
    - 참고문헌 항목, 그림·표 캡션: 마침표로 끝나지 않는다
    - 각주 바로 앞 문단: 각주 블록이 끼어들어 페이지 경계에서 닫힌 것이지 잘린 게 아니다
    """
    m = _REFS.search(md)
    body = md[:m.start()] if m else md
    blocks = [p.strip() for p in body.split("\n\n") if p.strip()]
    out = []
    for i, p in enumerate(blocks):
        nxt = blocks[i + 1] if i + 1 < len(blocks) else ""
        if len(p) <= 80 or p.lstrip().startswith(("#", "|", ">", "!")):
            continue
        if _SKIP_PARA.match(p) or nxt.startswith(">"):
            continue
        out.append(p)
    return out


def truncated_ratio(md: str) -> float:
    """문장 중간에서 끊긴 문단의 비율. 추출 손상의 신호다."""
    paras = checked_paragraphs(md)
    if not paras:
        return 0.0
    return len([p for p in paras if not _ends_properly(p)]) / len(paras)


def score(md: str, raw_text: str, dropped_chars: int) -> Score:
    denom = norm_len(raw_text) - max(dropped_chars, 0)
    cov = norm_len(md) / denom if denom > 0 else 0.0
    tr = truncated_ratio(md)
    return Score(cov, tr, cov >= MIN_COVERAGE and tr <= MAX_TRUNCATED)


def _penalty(s: Score) -> float:
    """작을수록 좋은 추출. 보존율은 1.0에서 멀수록, 잘린 문단은 많을수록 나쁘다.

    보존율만 보면 순서 오류를 놓친다. 좌우 단이 한 줄에 섞이면 문자는 그대로라
    보존율이 1.0에 가깝지만 문장이 끊겨 잘린 문단 비율이 치솟는다(실측 0.577).
    """
    return abs(1.0 - s.coverage) + s.truncated


def better(current: Score, other: Score) -> bool:
    """other가 current보다 나은 추출인가. 기준 통과 여부가 먼저다."""
    if other.ok != current.ok:
        return other.ok
    return _penalty(other) < _penalty(current)


def report(s: Score, md: str) -> str:
    lines = ["# 추출 품질 리포트", "",
             f"- 문자 보존율: {s.coverage:.3f} (기준 {MIN_COVERAGE})",
             f"- 잘린 문단 비율: {s.truncated:.3f} (기준 {MAX_TRUNCATED})",
             f"- 판정: {'통과' if s.ok else '미달 — 번역을 시작하지 않음'}", ""]
    bad = [p[:100] for p in checked_paragraphs(md) if not _ends_properly(p)]
    if bad:
        lines += ["## 잘린 것으로 의심되는 문단", ""] + [f"- …{b}" for b in bad[:20]]
    return "\n".join(lines) + "\n"
