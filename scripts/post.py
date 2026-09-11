#!/usr/bin/env python3
"""KorDocAI 출력 후처리.

KorDocAI는 읽기 순서와 머리글·바닥글을 해결해 주지만 한 줄을 한 문단으로 내놓는다.
문단 경계·폰트 크기는 PyMuPDF 블록에서 정답지를 만들어 복원한다.
레이아웃 판단은 하지 않는다 — 그건 KorDocAI가 이미 했다.
"""
import re, statistics
from collections import defaultdict
from dataclasses import dataclass, field

import figures
import quality


def work_stem(name: str) -> str:
    """작업 폴더 이름. 공백·한글·기호를 밑줄로 바꾼다.

    경로에 공백이 있으면 도구마다 다르게 다뤄 폴더가 갈린다. 규칙은 여기 한 곳에만 둔다 —
    extract.py와 app.py가 다른 규칙을 쓰면 웹 UI가 엉뚱한 폴더를 보며 진행률이 멈춘다.
    """
    return re.sub(r"[^\w,.-]+", "_", name).strip("_")


def key(text: str) -> str:
    """줄 대조용 키. 공백·구두점 차이를 무시한다."""
    return re.sub(r"\W+", "", text).lower()[:40]


@dataclass
class Oracle:
    starts: set = field(default_factory=set)      # 문단 첫 줄 키
    headings: set = field(default_factory=set)    # 제목으로 판정된 줄 키
    sizes: dict = field(default_factory=dict)     # 줄 키 → 폰트 크기
    body_size: float = 0.0                        # 본문 폰트 중앙값
    page_last: dict = field(default_factory=dict) # 페이지 → 마지막 줄 키
    seq: list = field(default_factory=list)       # (줄 키, 문단 시작 여부) 문서 순서
    notes: set = field(default_factory=set)        # 각주로 판정된 줄 키


MARGIN = 0.08     # page_last를 고를 때 무시할 위·아래 여백 비율(머리글·바닥글 자리)
INDENT_PT = 6.0   # 단 왼쪽 기준선보다 이만큼 들어가면 문단 첫 줄로 본다
QUOTE_INDENT_TOL = 3.0  # 인용 블록으로 이어 붙일 때 허용하는 들여쓰기 차이
                  # (실측: 본문 x0 흔들림 ±2pt, 문단 들여쓰기 약 10pt)
SHORT_TAIL_PT = 25.0  # 단 오른쪽 끝에서 이만큼 못 미치면 문단 마지막 줄로 본다
HEADING_MIN = 1.08    # 본문 중앙값 대비 이 배 이상이면 제목 후보(맥락 조건 필요)
HEADING_STRONG = 1.25 # 이 배 이상이면 맥락과 무관하게 제목
FOOTNOTE_RATIO = 0.85 # 본문 중앙값 대비 이 배 이하면 각주
_SENT_END = tuple(".!?\"')]”’")


LETTER_RATIO = 0.70          # 제목으로 인정하려면 공백 뺀 글자 중 이 비율 이상이 문자여야 한다
# 낱말처럼 보이는 덩어리. 로마자는 세 글자 이상을 요구하고, 두 글자 낱말이 흔한
# 한글·한자는 두 글자로 인정한다(`그림 개요` 같은 제목을 잔재로 버리면 안 된다).
_WORDISH = re.compile(r"[^\W\d_]{3,}|[가-힣ㄱ-ㆎ一-鿿]{2,}")


def looks_like_text(s: str) -> bool:
    """읽을 수 있는 글인가. 스캔 잔재가 제목으로 승격되는 것을 막는다.

    스캔본은 그림·로고의 잔재가 '큰 글자로 된 짧은 줄'로 남아 제목 조건을 그대로
    만족한다(Teece 실측: `## ?S.SZ o .2`, `## Isl11?`, `## C0 g`, `## il`,
    `## * lnf?rSc??Tic??`). 이런 줄이 문단 한가운데에 끼면 문장이 갈린다.

    진짜 제목은 글자가 대부분이고 낱말을 이룬다 — `DAVID J. TEECE*`도 공백 뺀 13자 중
    11자가 문자다(85%). 잔재는 절반을 못 넘는다(`?S.SZ o .2` 40%, `C0 g` 50%).
    """
    body = [c for c in s if not c.isspace()]
    if not body:
        return False
    letters = sum(1 for c in body if c.isalpha())
    return letters / len(body) >= LETTER_RATIO and bool(_WORDISH.search(s))


def is_scan_debris(line, body_size) -> bool:
    """본문보다 큰 글자로 된 짧은 줄인데 읽을 수가 없다 — 그림·로고의 OCR 잔재다.

    제목으로 승격되는 것만 막아서는 부족하다. 강등되어도 여전히 별개 문단으로 남아
    문장 사이에 끼기 때문이다(Teece 실측: `…as routines and` / `?S.SZ o .2` / 이어지는
    본문). 아예 빼야 앞뒤가 한 문단으로 이어진다.

    크기 조건을 함께 보는 이유는 표 안 수치(`2.6 mil. 30.5%`)나 수식 조각처럼 읽을 수는
    없지만 본문 크기인 줄을 남겨두기 위해서다. 그것들은 잔재가 아니라 내용이다.
    """
    t = line["text"].strip()
    return bool(body_size and line["size"] and len(t) < 80
                and line["size"] >= body_size * HEADING_MIN
                and not looks_like_text(t))


_XREF_CLOSE = re.compile(r"^(figure|table|그림|표)\s*\d+\s*\)", re.I)


def is_figure_xref(text: str, prev_text: str) -> bool:
    """`Figure N)`이 캡션이 아니라 본문 속 상호참조인가.

    앞 줄이 여는 괄호를 닫지 않은 채 끝났으면 이 줄은 그 괄호를 닫는 본문이다
    (Teece 실측: `…the level of economic profits it can earn (see` /
    `Figure 4). Furthermore,…`가 캡션으로 오인되어 문장이 갈렸다).

    앞 문장이 끝났는지만 보면 안 된다. 진짜 캡션도 그림 축 라벨 바로 뒤에 오므로
    앞 줄이 문장부호로 끝나지 않는다(Peteraf 실측: `Diversification` /
    `Figure 4. The determination of…`). 닫히지 않은 괄호가 둘을 가른다.
    """
    return bool(_XREF_CLOSE.match(text.strip())
                and prev_text.count("(") > prev_text.count(")"))


_NUMBER_ONLY = re.compile(r"^[\[\(]?\d{1,4}[\]\)]?$")


def is_page_number(line, height) -> bool:
    """위·아래 여백에 홀로 놓인 숫자인가.

    반복 판정으로는 못 잡는다 — 쪽마다 값이 달라서다(`repeat_norm('1342')`은 '#'이
    되지만 다른 쪽 러닝헤드는 '# d. j. teece'라 서로 다른 항목이 된다). 본문에 남으면
    본문보다 큰 글자라 제목으로 승격되어 문장을 가른다(Teece 실측: p25 상단 6% 지점의
    `1342`가 `## 1342`가 되어 문장 한가운데에 끼었다).
    """
    return bool(_NUMBER_ONLY.match(line["text"].strip())
                and not (height * MARGIN < line["y0"] < height * (1 - MARGIN)))


# CMR(Computer Modern Roman)은 뺀다 — 순수 LaTeX 논문은 본문도 CMR로 찍어서
# 넣으면 본문 줄이 통째로 수식으로 잡힌다. 수식만 쓰는 폰트만 센다.
_MATH_FONT = re.compile(r"CM(MI|SY|EX)|MSAM|MSBM|StandardSymL|Symbol|Math", re.I)


def _math_ratio(spans) -> float:
    """줄에서 수학 폰트로 조판된 문자의 비율.

    TeX 논문은 수식을 Computer Modern 수학 폰트(CMMI·CMSY·CMEX)로 찍는다.
    본문 폰트와 확실히 갈리므로 좌표보다 믿을 수 있는 신호다(When Does 실측:
    본문 NimbusRomNo9L-Regu 20,724자 대 CMMI10·CMSY10·StandardSymL).
    """
    total = sum(len(sp["text"]) for sp in spans)
    if not total:
        return 0.0
    return sum(len(sp["text"]) for sp in spans
               if _MATH_FONT.search(sp.get("font", ""))) / total


def page_lines(page) -> list:
    """페이지의 텍스트 줄을 좌표·크기와 함께 뽑는다."""
    out = []
    for b in page.get_text("dict")["blocks"]:
        if b.get("type") != 0:
            continue
        for ln in b["lines"]:
            txt = "".join(sp["text"] for sp in ln["spans"]).strip()
            if not txt:
                continue
            sizes = [sp["size"] for sp in ln["spans"] if sp["size"] >= 2.0]
            out.append({"x0": ln["bbox"][0], "x1": ln["bbox"][2],
                        "y0": ln["bbox"][1], "y1": ln["bbox"][3],
                        "text": txt, "size": statistics.median(sizes) if sizes else 0.0,
                        "math": _math_ratio(ln["spans"])})
    return out


def _columns_of(lines: list, width: float) -> list:
    """줄을 단별로 나눠 y 오름차순으로 돌려준다. 1단이면 리스트 하나.

    두 단에 걸친 줄(제목·초록)은 좌단 앞에 따로 둔다. 논문 첫 본문 쪽은
    전면 폭 제목·초록 아래에 2단이 오는 혼합 레이아웃이라 이 구분이 필요하다.
    """
    mid = width / 2
    full, left, right = [], [], []
    for l in lines:
        if (l["x1"] - l["x0"]) > 0.6 * width:
            full.append(l)
        elif (l["x0"] + l["x1"]) / 2 < mid:
            left.append(l)
        else:
            right.append(l)
    if not left or not right:
        return [sorted(full + left + right, key=lambda l: l["y0"])]
    cols = [sorted(full, key=lambda l: l["y0"])] if full else []
    cols.append(sorted(left, key=lambda l: l["y0"]))
    cols.append(sorted(right, key=lambda l: l["y0"]))
    return cols


def ordered_lines(doc):
    """문서를 읽는 순서대로 줄을 돌려준다. 반환: (줄 목록, 본문 폰트 중앙값, 영역 목록)

    - 러닝헤드·바닥글은 뺀다. 결과물에서 지워지므로 정답지에도 있으면 안 된다.
    - 그림·표 영역 안의 줄은 뺀다. 그 영역은 이미지로 잘라 넣으므로 텍스트로도
      실리면 중복이고, 대개 OCR 잔재라 본문을 더럽힌다.
    - 각주는 해당 페이지 끝으로 모은다. 각주는 단 하단에 있어서 그대로 두면
      본문 문단 한가운데를 갈라놓는다(본문은 다음 단으로 이어지는데 그 사이에 끼어든다).

    줄 항목은 (페이지, 줄, 단 왼쪽 기준선, 단 오른쪽 끝, 페이지 높이)다.
    """
    repeated = repeated_norms(doc)
    all_sizes = [l["size"] for pno in range(doc.page_count)
                 for l in page_lines(doc[pno]) if l["size"]]
    body_size = statistics.median(all_sizes) if all_sizes else 0.0
    # 본문 크기 범위는 문서 전체 분포에서 구한다. 페이지 단위로는 표·그림만 있는
    # 쪽에서 엉뚱한 범위가 나온다.
    band = figures.body_band(all_sizes, body_size)

    out, regions_by_page = [], {}
    for pno in range(doc.page_count):
        page = doc[pno]
        height, width = page.rect.height, page.rect.width
        lines = [l for l in page_lines(page)
                 if repeat_norm(l["text"]) not in repeated
                 and not is_page_number(l, height)
                 and not is_scan_debris(l, body_size)]
        regions = figures.plan(page, lines, body_size, pno, band)
        if regions:
            regions_by_page[pno] = regions
            lines = [l for l in lines if not figures.covers(regions, l)]
        # 이 페이지에서 본문 크기 줄이 끝나는 y. 각주는 그 아래에 있고, 그림 라벨은
        # 본문 사이에 끼어 있다 — 크기만으로는 못 가르는 둘을 위치가 갈라준다.
        body_ys = [l["y0"] for l in lines
                   if l["size"] and band[0] <= l["size"] <= band[1]]
        body_floor = max(body_ys) if body_ys else 0.0
        body, notes = [], []
        for col in _columns_of(lines, width):
            if not col:
                continue
            # 단 왼쪽 기준선. 줄이 많으면 최빈값이 정확하지만, 줄이 적은 단에서는
            # 들여쓴 줄이 기준선이 되어버린다(두 줄짜리 단 [56, 48]의 mode는 56).
            xs = sorted(round(l["x0"]) for l in col)
            edge = statistics.mode(xs) if len(xs) >= 8 else xs[0]
            right_edge = max(l["x1"] for l in col)
            for l in col:
                if not key(l["text"]):
                    continue
                item = (pno, l, edge, right_edge, height)
                # 캡션은 글자가 작아도 각주가 아니다 — 그림 바로 아래 자리를 지켜야 한다
                # 비율 임계값만 보면 양자화된 크기에서 어긋난다. Bresnahan은 본문 8pt,
                # 각주 7pt인데 상한이 6.8pt라 각주 66줄 중 62줄이 본문으로 읽혔고,
                # 그 각주가 본문 문단 한가운데에 박혀 문단 44개를 갈랐다(잘린 문단 0.174).
                # 본문 밴드보다 작고 본문이 끝난 아래에 있으면 각주로 본다.
                below_body = bool(l["size"] and l["size"] < band[0]
                                  and l["y0"] > body_floor)
                is_note = (body_size and l["size"]
                           and l["y0"] > height * 0.4
                           and not figures.CAPTION_RE.match(l["text"].strip())
                           and (l["size"] <= body_size * FOOTNOTE_RATIO or below_body))
                if is_note:
                    l["note"] = True          # is_footnote가 `>` 표시에 쓴다
                (notes if is_note else body).append(item)
        out.extend(body + notes)
    return out, body_size, regions_by_page


def build_oracle(doc) -> Oracle:
    """문단 시작 줄과 줄별 폰트 크기를 알아낸다.

    블록 경계를 문단 경계로 믿으면 안 된다 — 실제 저널 PDF에서는 한 문단이 여러
    블록으로 쪼개진다(Peteraf에서 `minor points.`가 별도 블록으로 잡혔다).
    조판이 실제로 쓰는 신호를 본다: 첫 줄 들여쓰기, 그리고 단 끝까지 못 채운 마지막 줄.
    """
    o = Oracle()
    doc_lines, o.body_size, _regions = ordered_lines(doc)
    # 제목 판정에 쓸 본문 크기 범위. HEADING_MIN(1.08)이 BODY_HI(1.12)보다 낮아서
    # 1.08~1.12 구간은 '본문이면서 제목 후보'가 된다. When Does(2026)는 본문이
    # 10.91(821줄)과 11.96(275줄) 두 크기로 갈리는데, 11.96이 이 구간에 들어가
    # 문장이 끝난 직후의 짧은 본문 조각이 제목으로 오인됐다(`## tion.` 등 11건).
    band_hi = figures.body_band([l["size"] for _p, l, *_r in doc_lines if l["size"]],
                                o.body_size)[1]

    # prev를 단·페이지 경계 너머로 이어간다. 문단은 단을 넘어 계속되므로
    # 새 단의 첫 줄을 무조건 문단 시작으로 보면 문장이 끊긴다.
    prev, prev_right, prev_edge = None, 0.0, 0.0
    force_next, prev_heading = False, False
    for pno, l, edge, right_edge, height in doc_lines:
        k = key(l["text"])
        if l["size"]:
            o.sizes.setdefault(k, l["size"])
        if l.get("note"):
            o.notes.add(k)
        # 크기만으로 제목을 가르면 안 된다. 스캔 텍스트 레이어는 본문 글자 크기가
        # 7.65~9.07로 흔들려서(중앙값 8.31) 본문 줄이 제목으로 오인된다.
        # 제목은 문장 도중에 나오지 않는다는 맥락 조건을 함께 본다.
        context_ok = (prev is None or prev_heading
                      or prev["text"].rstrip().endswith(_SENT_END))
        # 제목은 단 폭을 채우지 않는다. 이 조건이 없으면 줄바꿈된 본문 줄이
        # 크기 흔들림만으로 제목이 되어 `## While only tradeable resources can be`
        # 같은 가짜 제목이 생긴다.
        col_width = right_edge - edge
        short_line = col_width <= 0 or (l["x1"] - l["x0"]) < col_width * 0.7
        heading = bool(l.get("kind") != "table" and o.body_size
                       and len(l["text"]) < 80 and short_line
                       and looks_like_text(l["text"])
                       and l["size"] > band_hi        # 본문 범위 안이면 제목이 아니다
                       and (l["size"] >= o.body_size * HEADING_STRONG
                            or (l["size"] >= o.body_size * HEADING_MIN and context_ok)))
        # 들여쓰기는 문단 첫 줄의 신호지만, 인용 블록은 모든 줄이 똑같이 들여써 있다
        # (실측: 본문 x0=267, 인용문 전 줄 x0=279). 같은 위치로 이어지면 첫 줄만 문단을 연다.
        #
        # 절대 x0가 아니라 단 기준선 대비 들여쓰기로 잰다. 절대값으로 재면 인용문이
        # 단·페이지를 넘어갈 때 차이가 단 폭만큼 벌어져 무조건 실패한다(Teece p20 실측:
        # x0 71.5(기준선 57) → 300.6(기준선 288), 차이 229.8pt. 들여쓰기로는 14.5 vs 12.6).
        # 오차도 1.5pt로는 좁다 — 스캔본은 같은 인용문 안에서 x0가 3.6pt까지 흔들린다
        # (Teece p29 Porter 인용문 65.4~69.0). 6줄 중 5줄에서 가드가 실패했다.
        indent_gap = l["x0"] - edge
        prev_indent = (prev["x0"] - prev_edge) if prev is not None else 0.0
        same_indent_run = (prev is not None and prev_indent >= INDENT_PT
                           and abs(prev_indent - indent_gap) <= QUOTE_INDENT_TOL)
        indented = indent_gap >= INDENT_PT and not same_indent_run
        after_short = (prev is not None and prev["text"].endswith(_SENT_END)
                       and prev["x1"] < prev_right - SHORT_TAIL_PT)
        # 본문 크기에서 각주 크기로 내려가면 각주가 시작된 것이다. 본문 바로 뒤에
        # 붙은 각주는 들여쓰기도 짧은 꼬리도 없어서 이 신호가 없으면 본문에 섞인다.
        # 직전 줄과의 상대 비교는 쓰지 않는다 — 스캔 텍스트는 줄마다 크기가
        # ±0.7pt 흔들려서 본문 안에서도 10% 낙차가 생긴다.
        size_drop = (prev is not None and o.body_size and l["size"] and prev["size"]
                     and l["size"] <= o.body_size * FOOTNOTE_RATIO
                     and prev["size"] > o.body_size * FOOTNOTE_RATIO)
        # 반대로 각주 크기에서 본문 크기로 올라가면 각주가 끝난 것이다.
        # 없으면 각주 문단이 뒤따르는 본문을 통째로 삼킨다.
        size_rise = (prev is not None and o.body_size and l["size"] and prev["size"]
                     and prev["size"] <= o.body_size * FOOTNOTE_RATIO
                     and l["size"] > o.body_size * FOOTNOTE_RATIO)
        # 캡션은 언제나 문단을 연다. 가운데 정렬이라 단 분류가 흔들리면 들여쓰기
        # 신호를 잃고 앞 문단에 흡수되는데, 그러면 그림을 붙일 자리를 잃는다.
        #
        # 단, 닫히지 않은 괄호를 잇는 `Figure N)`은 캡션이 아니라 본문 상호참조다.
        is_caption = bool(figures.CAPTION_RE.match(l["text"].strip())
                          and not is_figure_xref(l["text"], prev["text"] if prev else ""))
        is_table = l.get("kind") == "table"
        is_start = bool(is_table or is_caption or prev is None or indented or after_short
                        or heading or force_next or size_drop or size_rise)
        if is_start:
            o.starts.add(k)
            if height * MARGIN < l["y0"] < height * (1 - MARGIN):
                o.page_last[pno] = k
        # 이 줄의 판정을 그대로 기록한다. 누적 집합을 조회하면 같은 문구가
        # 앞에서 문단 시작이었다는 이유로 여기서도 시작이 되어버린다.
        o.seq.append((k, is_start))
        if heading:
            o.headings.add(k)
        force_next = heading
        prev_heading = heading          # 제목 다음 줄은 본문 문단의 시작이다
        prev, prev_right, prev_edge = l, right_edge, edge
    return o


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
    seq, i = oracle.seq, 0
    paras, cur, k0 = [], "", ""
    for u in units(md):
        k = key(u)
        # 위치를 맞춰가며 판정한다. 키 집합만 보면 'competition.' 같은 짧은 줄이
        # 문서 다른 곳에서 문단 시작이라는 이유로 여기서도 시작으로 오인된다.
        j = next((x for x in range(i, min(i + 3, len(seq))) if seq[x][0] == k), None)
        if j is not None:
            at_start, i = seq[j][1], j + 1
        else:
            at_start = k in oracle.starts
        starts_new = (not cur) or at_start or u.startswith(("#", "!", "|", ">"))
        if starts_new:
            if cur:
                paras.append((k0, cur))
            cur, k0 = u, k
        else:
            cur = join_unit(cur, u)
    if cur:
        paras.append((k0, cur))
    return paras


def is_footnote(key0: str, oracle) -> bool:
    """각주 문단인가. `>` 표시를 붙일지 가른다.

    크기 비율만 보면 ordered_lines가 위치로 골라낸 각주를 놓친다 — 그러면 각주가
    본문 뒤로 옮겨지기는 하되 `> **각주 N**` 표시를 받지 못해 본문으로 번역된다.
    """
    if key0 in oracle.notes:
        return True
    size = oracle.sizes.get(key0)
    if size is None or not oracle.body_size:     # 모르면 본문으로 둔다
        return False
    return size <= oracle.body_size * FOOTNOTE_RATIO


def mark_footnotes(paras: list, oracle) -> list:
    """각주 문단을 인용 블록으로 감싼다. 위치는 옮기지 않는다 —
    KorDocAI가 이미 해당 페이지 본문 뒤에 번호순으로 모아뒀다."""
    out = []
    for k0, p in paras:
        if figures.CAPTION_RE.match(p.strip()) or not is_footnote(k0, oracle):
            out.append(p)
            continue
        m = re.match(r"^(\d+)\s*\.?\s*(.*)$", p, re.S)   # `2. Ferguson…`의 마침표까지
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
            dropped += quality.norm_len(p)
        else:
            kept.append((k0, p))
    return kept, dropped


def block_text(b) -> str:
    return "\n".join("".join(sp["text"] for sp in ln["spans"]).strip()
                     for ln in b["lines"]).strip()


def repeat_norm(text: str) -> str:
    """반복 판정용 정규화. 페이지 번호가 달라도 같은 러닝헤드로 보이게 숫자를 지운다.

    쪽 번호는 러닝헤드에 붙어 나오기도 하고(`1320 D. J. Teece`) 별개 줄로 떨어지기도
    한다(Teece p25 실측: `1342` / `D. J. Teece`). 숫자를 `#`으로 바꾸기만 하면 두 꼴이
    `# d. j. teece`와 `d. j. teece`로 갈려 서로 다른 항목이 되고, 쪽마다 한 번씩만
    세어져 반복으로 걸리지 않는다. 앞뒤에 홀로 붙은 숫자는 통째로 지운다.
    """
    t = re.sub(r"\s+", " ", text).strip().lower()
    t = re.sub(r"^\d+\s+|\s+\d+$", "", t)
    return re.sub(r"\d+", "#", t).strip()


_MD_HEAD = re.compile(r"^#{1,6}\s*")


def _leading_repeat_words(s: str, repeated: set, max_words: int = 20) -> int:
    """s 앞머리에서 러닝헤드로 판정되는 단어 수. 없으면 0.

    러닝헤드는 짧다. 단어를 뒤에서부터 줄여가며 repeat_norm으로 맞춰본다 —
    같은 정규화를 쓰므로 쪽 번호가 붙은 꼴도 함께 걸린다.
    """
    words = s.split()
    for n in range(min(len(words), max_words), 0, -1):
        if repeat_norm(" ".join(words[:n])) in repeated:
            return n
    return 0


def strip_running_heads(paras: list, repeated: set) -> list:
    """kordoc 본문에 남은 러닝헤드를 지운다. 단독이면 문단째, 붙어 있으면 앞부분만.

    ordered_lines()는 정답지에서만 러닝헤드를 뺀다. kordoc 마크다운은 걸러지지 않아
    워터마크가 제목(`# Preprint not peer reviewed`)으로 남고, 페이지 경계마다 문단을
    갈라놓았다(When Does 2026 실측: 40회 등장, 잘린 문단 0.198).
    repeated_chars()가 그 글자 수를 이미 분모에서 빼므로, 본문에서도 지워야
    보존율이 맞는다(지우지 않아 1.057이 나왔다).
    """
    out = []
    for k0, para in paras:
        body = _MD_HEAD.sub("", para.strip())
        n = _leading_repeat_words(body, repeated)
        if not n:
            out.append((k0, para))
            continue
        rest = " ".join(body.split()[n:])
        if rest:                     # 본문에 붙어 있던 것 — 머리글만 떼고 살린다
            out.append((k0, rest))
        # 러닝헤드뿐인 문단은 버린다
    return out


def _repeated(doc, min_pages: int = 3):
    """여러 쪽에 반복되는 짧은 줄(러닝헤드·바닥글). 반환: (정규화 집합, 문자 수)

    블록 단위로 세면 두 줄짜리 바닥글의 둘째 줄이 걸러지지 않는다 —
    필터는 줄 단위로 도는데 블록 정규화 문자열은 두 줄이 합쳐진 형태이기 때문이다.
    """
    seen = defaultdict(lambda: [0, set()])
    for pno in range(doc.page_count):
        for l in page_lines(doc[pno]):
            txt = l["text"]
            if not txt or len(txt) > 120:
                continue
            entry = seen[repeat_norm(txt)]
            entry[0] += quality.norm_len(txt)
            entry[1].add(pno)
    hits = {n: c for n, (c, pages) in seen.items() if len(pages) >= min_pages}
    return set(hits), sum(hits.values())


def region_chars(doc, regions_by_page: dict) -> int:
    """그림·표 영역으로 잘라낸 텍스트의 문자 수.

    이미지로 옮겼으므로 본문에 없는 것이 정상이다. 머리말·바닥글과 같이
    손실 게이트의 분모에서 빼지 않으면 의도적 제거가 유실로 집계된다.
    """
    if not regions_by_page:
        return 0
    total = 0
    for pno, regions in regions_by_page.items():
        for l in page_lines(doc[pno]):
            if figures.covers(regions, l):
                total += quality.norm_len(l["text"])
    return total


def repeated_norms(doc, min_pages: int = 3) -> set:
    return _repeated(doc, min_pages)[0]


def repeated_chars(doc, min_pages: int = 3) -> int:
    """반복 요소의 문자 수. 손실 게이트의 분모에서 빼지 않으면
    의도적으로 버린 텍스트가 유실로 집계되어 멀쩡한 추출이 미달 판정을 받는다."""
    return _repeated(doc, min_pages)[1]


MIN_IMG_RATIO, MAX_IMG_RATIO = 0.03, 0.60


def sanitize(stem: str) -> str:
    """공백을 밑줄로 바꾼다. 경로에 공백이 있으면 이미지가 엉뚱한 폴더에 저장된다."""
    return re.sub(r"\s+", "_", stem.strip())


def strip_kordoc_images(md: str) -> str:
    """KorDocAI가 남긴 이미지 링크는 전면 스캔 배경이므로 전부 버린다."""
    keep = [u for u in md.split("\n\n") if not re.fullmatch(r"!\[[^\]]*\]\([^)]*\)", u.strip())]
    return "\n\n".join(keep)


def pick_images(doc, skip_pages=()) -> list:
    """면적 3~60%이고 한 페이지에만 나오는 이미지만 고른다.

    하한은 로고(실측 0.62%, 1.71%)를, 상한은 전면 스캔 배경(91.32%)을 걸러낸다.
    """
    pages_of = defaultdict(set)
    cand = []
    for pno in range(doc.page_count):
        page = doc[pno]
        area = page.rect.width * page.rect.height
        for img in page.get_images(full=True):
            xref = img[0]
            for r in page.get_image_rects(xref):
                pages_of[xref].add(pno)
                cand.append((pno, xref, r, (r.width * r.height) / area))
    out = []
    for pno, xref, r, ratio in cand:
        if pno in skip_pages or len(pages_of[xref]) > 1:
            continue
        if MIN_IMG_RATIO <= ratio <= MAX_IMG_RATIO:
            out.append((pno, xref, r))
    return out


def save_images(doc, picks, img_dir, stem: str) -> dict:
    img_dir.mkdir(parents=True, exist_ok=True)
    by_page = defaultdict(list)
    for i, (pno, xref, _r) in enumerate(picks, 1):
        d = doc.extract_image(xref)
        name = f"{sanitize(stem)}-p{pno + 1:03d}-{i:02d}.{d['ext']}"
        (img_dir / name).write_bytes(d["image"])
        by_page[pno].append(f"![](images/{name})")
    return dict(by_page)


def insert_images(paras: list, by_page: dict, oracle) -> list:
    """이미지를 해당 페이지의 마지막 본문 문단 뒤에 넣는다."""
    if not by_page:
        return list(paras)
    tail = {oracle.page_last.get(p): links for p, links in by_page.items() if oracle.page_last.get(p)}
    out, placed = [], set()
    for p in paras:
        out.append(p)
        for k, links in tail.items():
            if k not in placed and k in key(p):
                out.extend(links)
                placed.add(k)
    for k, links in tail.items():          # 자리를 못 찾은 이미지는 유실 대신 끝에 붙인다
        if k not in placed:
            out.extend(links)
    return out


def _is_body(text: str) -> bool:
    return not text.lstrip().startswith(("#", ">", "!", "|"))


def merge_continuations(texts: list) -> list:
    """페이지·단을 넘어 이어지는 문장을 한 문단으로 잇는다.

    각주를 페이지 끝으로 모으면서 본문 문단이 각주 블록에 막혀 닫힌다. 다음 쪽의
    이어지는 부분이 별도 문단이 되면 번역자가 문장 조각을 따로 번역하게 된다.
    끼어든 각주·이미지는 버리지 않고 합쳐진 문단 뒤로 옮긴다.
    """
    out, i = [], 0
    while i < len(texts):
        p, moved = texts[i], []
        i += 1
        # 이은 결과를 다시 본다. 세 조각으로 갈린 문단은 한 번만 이으면 여전히
        # 문장 중간에서 끊긴다(When Does 2026 실측: 남은 잘린 문단 27건 중 12건).
        while _is_body(p) and not p.rstrip().endswith(_SENT_END) and i < len(texts):
            j, skipped, blocked = i, [], False
            while j < len(texts) and not _is_body(texts[j]):
                if texts[j].lstrip().startswith("#"):
                    blocked = True      # 제목을 넘어서는 잇지 않는다 — 절이 실제로 끝난 자리다
                    break
                skipped.append(texts[j])
                j += 1
            # 소문자로 시작해야 이어지는 문장이다. 새 문단은 대문자나 인용부호로 시작한다.
            if blocked or j >= len(texts) or not _is_continuation(texts[j]):
                break
            p = join_unit(p, texts[j])
            moved.extend(skipped)       # 끼어든 각주·이미지는 합친 문단 뒤로 옮긴다
            i = j + 1
        out.append(p)
        out.extend(moved)
    return out


_MATH_UNIT_MAX = 130
_MATH_OP = re.compile(r"[=≈≤≥∑∏∫→←⇒∂±×÷∼≡∥]")
_PROSE_WORD = re.compile("[A-Za-z]{4,}")   # 산문 낱말 — 4자 이상 알파벳 연속


def is_math_block(text: str) -> bool:
    """이 문단이 통째로 수식인가.

    kordoc은 수식을 잘게 조각내 독립 문단으로 내놓는다(When Does 실측: 단위
    1253개 중 75개가 수식 조각이었고 눈으로 확인한 결과 전부 실제 수식이었다).
    그 조각이 본문 문단 사이에 끼어 문단을 갈랐다.

    산문 낱말 수를 함께 본다 — 인라인 수식이 든 본문 문단은 건드리지 않는다.
    본문을 지우면 번역이 불가능해진다. `# ∑`처럼 제목으로 잡힌 조각도 있으므로
    제목 표시는 벗겨 놓고 판정한다.
    """
    t = _MD_HEAD.sub("", text.strip())
    if not t or len(t) > _MATH_UNIT_MAX or t.startswith((">", "!", "|")):
        return False
    return bool(_MATH_OP.search(t)) and len(_PROSE_WORD.findall(t)) <= 3


def drop_math_blocks(paras: list) -> tuple:
    """통째로 수식인 문단을 본문에서 뺀다. 반환: (남은 문단, 뺀 글자 수)

    수식은 figures가 영역 이미지로 옮겼으므로 본문에 텍스트로도 남으면 중복이고,
    대개 뭉개져 읽을 수 없다(`A˙ = θ Sη Aφ0+φ1E f t. (6) f t f t`).
    조각이 빠지면 갈라진 앞뒤 문단이 merge_continuations로 다시 붙는다.
    """
    out, chars = [], 0
    for k0, para in paras:
        if is_math_block(para):
            chars += quality.norm_len(para)
            continue
        out.append((k0, para))
    return out, chars


_CONT_SYMBOL = ("−→", "→", "⇒", "≈", "≡", "∑", "≤", "≥")
_OPEN_QUOTE = ("“", "‘", chr(34), chr(39))


def _is_continuation(text: str) -> bool:
    """이어지는 조각인가.

    새 문단은 대문자나 인용부호로 시작한다. 다만 화살표·연산자로 시작하는 줄은
    문장을 열 수 없다 — 앞 문단에서 이어진 수식 사슬이다(When Does 실측:
    `−→ coherent stop–start wave.`, `−→ laboratory and researcher incentives`).
    """
    t = text.lstrip()
    if re.match("^[a-z]", t) or t.startswith(_CONT_SYMBOL):
        return True
    # 여는 인용부호 뒤가 소문자면 문장 도중이다. 인용으로 문단을 열 때는
    # 안쪽이 대문자로 시작한다(When Does 실측: `“emergence score” by combining…`).
    if t[:1] in _OPEN_QUOTE:
        return bool(re.match("[a-z]", t[1:].lstrip()))
    return False


def _norm_flat(t: str) -> str:
    """앵커 대조용 정규화. 공백·구두점 차이를 무시한다(key()와 달리 자르지 않는다)."""
    return re.sub(r"\W+", "", t).lower()


def insert_equation_links(texts: list, regions_by_page: dict) -> list:
    """수식 이미지를 바로 위 본문 줄을 품은 문단 뒤에 넣는다.

    수식에는 캡션이 없어 캡션 앵커를 쓸 수 없고, 페이지 단위 배치는 자리를 잃는다
    — 수식은 페이지 한가운데에 있다. 영역에 기록해 둔 앵커 텍스트로 문단을 찾는다.
    """
    eqs = []
    for pno in sorted(regions_by_page):
        for r in regions_by_page[pno]:
            if r.get("kind") == "equation":
                eqs.append((_norm_flat(r.get("after_text", "")), r["link"]))
    if not eqs:
        return texts
    out, used = [], set()
    for para in texts:
        out.append(para)
        flat = _norm_flat(para)
        for i, (anchor, link) in enumerate(eqs):
            if i not in used and anchor and anchor in flat:
                out.append(link)
                used.add(i)
    # 앵커를 못 찾은 수식도 잃지 않는다
    out.extend(link for i, (_a, link) in enumerate(eqs) if i not in used)
    return out


def insert_region_links(texts: list, regions_by_page: dict) -> list:
    """잘라낸 그림 이미지를 캡션 문단 바로 앞에 넣는다."""
    anchors = {}
    for regions in regions_by_page.values():
        for r in regions:
            if r.get("cap_text"):
                anchors[key(r["cap_text"])] = r["link"]
    if not anchors:
        return texts
    out, used = [], set()
    for p in texts:
        k = key(p)
        for ak, link in anchors.items():
            if ak not in used and ak and k.startswith(ak[:20]):
                out.append(link)
                used.add(ak)
                break
        out.append(p)
    out.extend(link for ak, link in anchors.items() if ak not in used)
    return out


def postprocess(kordoc_md: str, doc, img_dir, stem: str):
    """KorDocAI 출력을 번역 가능한 마크다운으로 다듬는다. 반환: (markdown, stats)"""
    oracle = build_oracle(doc)
    _lines, _body, regions_by_page = ordered_lines(doc)
    md = strip_kordoc_images(kordoc_md)
    paras = rebuild_paragraphs(md, oracle)
    paras, dropped = drop_cover(paras)
    paras = strip_running_heads(paras, repeated_norms(doc))
    # 뺀 글자 수는 dropped에 더하지 않는다 — 잘라낸 수식 영역의 글자는
    # region_chars()가 이미 분모에서 빼므로 여기서 또 빼면 이중 차감이다.
    paras, _math_chars = drop_math_blocks(paras)

    cover = 0 if any(COVER_PAT.search(u) for u in units(kordoc_md)[:60]) else None
    picks = pick_images(doc, skip_pages=() if cover is None else (cover,))
    # 잘라낸 영역 안의 삽입 이미지는 중복이므로 뺀다
    picks = [(pno, xref, r) for pno, xref, r in picks
             if not figures.covers(regions_by_page.get(pno, []),
                                   {"x0": r.x0, "x1": r.x1, "y0": r.y0})]
    by_page = save_images(doc, picks, img_dir, stem) if picks else {}
    n_cropped = figures.render(doc, regions_by_page, img_dir)
    # 캡션 없는 영역(표)은 페이지 기준으로 배치한다
    for pno, regions in regions_by_page.items():
        for r in regions:
            if not r.get("cap_text") and r.get("kind") != "equation":
                by_page.setdefault(pno, []).append(r["link"])

    paras = [(k0, f"## {p}" if k0 in oracle.headings and not p.startswith("#") else p)
             for k0, p in paras]
    texts = mark_footnotes(paras, oracle)
    texts = merge_continuations(texts)
    texts = insert_equation_links(texts, regions_by_page)
    texts = insert_region_links(texts, regions_by_page)
    texts = insert_images(texts, by_page, oracle)
    n_notes = sum(1 for p in texts if p.startswith("> **각주"))
    dropped += repeated_chars(doc)                    # 지운 머리말·바닥글
    dropped += region_chars(doc, regions_by_page)     # 이미지로 옮긴 그림·표 안 글자
    return "\n\n".join(texts) + "\n", {"dropped_chars": dropped,
                                       "figures": len(picks) + n_cropped,
                                       "footnotes": n_notes}
