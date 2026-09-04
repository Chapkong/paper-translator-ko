#!/usr/bin/env python3
"""추출 품질 채점. 기준 미달이면 번역을 시작하지 않는다.

깨진 원문을 번역하면 토큰만 쓰고 결과도 못 쓴다. 여기서 막는 것이 가장 싸다.
"""
import re
from dataclasses import dataclass

MIN_COVERAGE = 0.97   # 문자 보존율 하한
MAX_TRUNCATED = 0.03  # 잘린 문단 비율 상한

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


def truncated_ratio(md: str) -> float:
    paras = [p.strip() for p in md.split("\n\n")
             if len(p.strip()) > 80 and not p.lstrip().startswith(("#", "|", ">", "!"))]
    if not paras:
        return 0.0
    return len([p for p in paras if not p.endswith(_ENDINGS)]) / len(paras)


def score(md: str, raw_text: str, dropped_chars: int) -> Score:
    denom = norm_len(raw_text) - max(dropped_chars, 0)
    cov = norm_len(md) / denom if denom > 0 else 0.0
    tr = truncated_ratio(md)
    return Score(cov, tr, cov >= MIN_COVERAGE and tr <= MAX_TRUNCATED)


def better(current: Score, other: Score) -> bool:
    """other가 current보다 나은 추출인가.

    보존율은 높을수록 좋은 것이 아니라 1.0에 가까울수록 좋다. 1을 크게 넘으면
    원문에 없는 문자(표 기호·중복 텍스트)가 늘어난 것이므로 나쁜 결과다.
    """
    return abs(1.0 - other.coverage) < abs(1.0 - current.coverage)


def report(s: Score, md: str) -> str:
    lines = ["# 추출 품질 리포트", "",
             f"- 문자 보존율: {s.coverage:.3f} (기준 {MIN_COVERAGE})",
             f"- 잘린 문단 비율: {s.truncated:.3f} (기준 {MAX_TRUNCATED})",
             f"- 판정: {'통과' if s.ok else '미달 — 번역을 시작하지 않음'}", ""]
    bad = [p.strip()[:100] for p in md.split("\n\n")
           if len(p.strip()) > 80 and not p.lstrip().startswith(("#", "|", ">", "!"))
           and not p.strip().endswith(_ENDINGS)]
    if bad:
        lines += ["## 잘린 것으로 의심되는 문단", ""] + [f"- …{b}" for b in bad[:20]]
    return "\n".join(lines) + "\n"
