#!/usr/bin/env python3
"""KorDocAI 출력 후처리.

KorDocAI는 읽기 순서와 머리글·바닥글을 해결해 주지만 한 줄을 한 문단으로 내놓는다.
문단 경계·폰트 크기는 PyMuPDF 블록에서 정답지를 만들어 복원한다.
레이아웃 판단은 하지 않는다 — 그건 KorDocAI가 이미 했다.
"""
import re, statistics
from collections import defaultdict
from dataclasses import dataclass, field


def key(text: str) -> str:
    """줄 대조용 키. 공백·구두점 차이를 무시한다."""
    return re.sub(r"\W+", "", text).lower()[:40]


@dataclass
class Oracle:
    starts: set = field(default_factory=set)      # 문단 첫 줄 키
    sizes: dict = field(default_factory=dict)     # 줄 키 → 폰트 크기
    body_size: float = 0.0                        # 본문 폰트 중앙값
    page_last: dict = field(default_factory=dict) # 페이지 → 마지막 줄 키


def build_oracle(doc) -> Oracle:
    o = Oracle()
    all_sizes = []
    for pno in range(doc.page_count):
        last = ""
        for b in doc[pno].get_text("dict")["blocks"]:
            if b.get("type") != 0:
                continue
            first = True
            for ln in b["lines"]:
                txt = "".join(sp["text"] for sp in ln["spans"]).strip()
                if not txt:
                    continue
                k = key(txt)
                if not k:
                    continue
                if first:
                    o.starts.add(k)
                    first = False
                sizes = [sp["size"] for sp in ln["spans"] if sp["size"] >= 2.0]
                if sizes:
                    med = statistics.median(sizes)
                    o.sizes.setdefault(k, med)
                    all_sizes.append(med)
                last = k
        if last:
            o.page_last[pno] = last
    o.body_size = statistics.median(all_sizes) if all_sizes else 0.0
    return o
