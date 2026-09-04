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


FOOTNOTE_RATIO = 0.85

COVER_PAT = re.compile(
    r"jstor|accessibility support|terms and conditions|about\.jstor\.org"
    r"|is collaborating with|not-for-profit|remediated|all use subject to", re.I)


def units(md: str) -> list:
    """KorDocAI 출력은 PDF 한 줄이 한 문단이다. 빈 줄 기준으로 쪼갠다."""
    return [u.strip() for u in md.split("\n\n") if u.strip()]


def join_unit(acc: str, part: str) -> str:
    """줄을 잇는다. 줄 끝 하이픈은 분철이므로 공백 없이 붙인다."""
    if not acc:
        return part
    if re.search(r"\w-$", acc):
        return acc[:-1] + part
    return acc + " " + part


def rebuild_paragraphs(md: str, oracle) -> list:
    """정답지의 문단 시작 줄에서만 새 문단을 연다.

    반환값은 (첫 줄 키, 문단 텍스트) 쌍이다. 폰트 크기 정답지가 줄 단위이므로
    각주를 판정하려면 문단이 자기 첫 줄의 키를 기억하고 있어야 한다.
    """
    paras, cur, k0 = [], "", ""
    for u in units(md):
        starts_new = (not cur) or key(u) in oracle.starts or u.startswith(("#", "!", "|", ">"))
        if starts_new:
            if cur:
                paras.append((k0, cur))
            cur, k0 = u, key(u)
        else:
            cur = join_unit(cur, u)
    if cur:
        paras.append((k0, cur))
    return paras


def is_footnote(key0: str, oracle) -> bool:
    size = oracle.sizes.get(key0)
    if size is None or not oracle.body_size:     # 모르면 본문으로 둔다
        return False
    return size <= oracle.body_size * FOOTNOTE_RATIO


def mark_footnotes(paras: list, oracle) -> list:
    """각주 문단을 인용 블록으로 감싼다. 위치는 옮기지 않는다 —
    KorDocAI가 이미 해당 페이지 본문 뒤에 번호순으로 모아뒀다."""
    out = []
    for k0, p in paras:
        if not is_footnote(k0, oracle):
            out.append(p)
            continue
        m = re.match(r"^(\d+)\s*(.*)$", p, re.S)
        out.append(f"> **각주 {m.group(1)}** {m.group(2)}" if m else f"> **각주** {p}")
    return out


def drop_cover(paras: list, limit: int = 60):
    """표지의 배너·약관 문단을 버린다. 서지 정보는 남는다.

    KorDocAI가 반복 바닥글을 이미 지웠으므로 남은 JSTOR 문구는 표지에만 있다.
    안전을 위해 문서 앞부분(limit개 문단)에서만 지운다.
    """
    kept, dropped = [], 0
    for i, (k0, p) in enumerate(paras):
        if i < limit and COVER_PAT.search(p):
            dropped += len(p)
        else:
            kept.append((k0, p))
    return kept, dropped
