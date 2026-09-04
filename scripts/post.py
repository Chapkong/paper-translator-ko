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


MARGIN = 0.08     # page_last를 고를 때 무시할 위·아래 여백 비율(머리글·바닥글 자리)
INDENT_PT = 6.0   # 단 왼쪽 기준선보다 이만큼 들어가면 문단 첫 줄로 본다
                  # (실측: 본문 x0 흔들림 ±2pt, 문단 들여쓰기 약 10pt)
SHORT_TAIL_PT = 25.0  # 단 오른쪽 끝에서 이만큼 못 미치면 문단 마지막 줄로 본다
HEADING_MIN = 1.08    # 본문 중앙값 대비 이 배 이상이면 제목 후보(맥락 조건 필요)
HEADING_STRONG = 1.25 # 이 배 이상이면 맥락과 무관하게 제목
FOOTNOTE_RATIO = 0.85 # 본문 중앙값 대비 이 배 이하면 각주
_SENT_END = tuple(".!?\"')]”’")


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
                        "text": txt, "size": statistics.median(sizes) if sizes else 0.0})
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

    out, regions_by_page = [], {}
    for pno in range(doc.page_count):
        page = doc[pno]
        height, width = page.rect.height, page.rect.width
        lines = [l for l in page_lines(page) if repeat_norm(l["text"]) not in repeated]
        regions = figures.plan(page, lines, body_size, pno)
        if regions:
            regions_by_page[pno] = regions
            lines = [l for l in lines if not figures.covers(regions, l)]
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
                is_note = (body_size and l["size"]
                           and l["size"] <= body_size * FOOTNOTE_RATIO
                           and l["y0"] > height * 0.4
                           and not figures.CAPTION_RE.match(l["text"].strip()))
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

    # prev를 단·페이지 경계 너머로 이어간다. 문단은 단을 넘어 계속되므로
    # 새 단의 첫 줄을 무조건 문단 시작으로 보면 문장이 끊긴다.
    prev, prev_right, prev_edge = None, 0.0, 0.0
    force_next, prev_heading = False, False
    for pno, l, edge, right_edge, height in doc_lines:
        k = key(l["text"])
        if l["size"]:
            o.sizes.setdefault(k, l["size"])
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
                       and (l["size"] >= o.body_size * HEADING_STRONG
                            or (l["size"] >= o.body_size * HEADING_MIN and context_ok)))
        # 들여쓰기는 문단 첫 줄의 신호지만, 인용 블록은 모든 줄이 똑같이 들여써 있다
        # (실측: 본문 x0=267, 인용문 전 줄 x0=279). 같은 위치로 이어지면 첫 줄만 문단을 연다.
        indent_gap = l["x0"] - edge
        prev_indent = (prev["x0"] - prev_edge) if prev is not None else 0.0
        same_indent_run = (prev is not None and prev_indent >= INDENT_PT
                           and abs(prev["x0"] - l["x0"]) <= 1.5)
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
        is_caption = bool(figures.CAPTION_RE.match(l["text"].strip()))
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
            dropped += quality.norm_len(p)
        else:
            kept.append((k0, p))
    return kept, dropped


def block_text(b) -> str:
    return "\n".join("".join(sp["text"] for sp in ln["spans"]).strip()
                     for ln in b["lines"]).strip()


def repeat_norm(text: str) -> str:
    """반복 판정용 정규화. 페이지 번호가 달라도 같은 러닝헤드로 보이게 숫자를 지운다."""
    return re.sub(r"\d+", "#", re.sub(r"\s+", " ", text)).strip().lower()


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
        p = texts[i]
        if _is_body(p) and not p.rstrip().endswith(_SENT_END):
            j, skipped, blocked = i + 1, [], False
            while j < len(texts) and not _is_body(texts[j]):
                if texts[j].lstrip().startswith("#"):
                    blocked = True      # 제목을 넘어서는 잇지 않는다 — 절이 실제로 끝난 자리다
                    break
                skipped.append(texts[j])
                j += 1
            # 소문자로 시작해야 이어지는 문장이다. 새 문단은 대문자나 인용부호로 시작한다.
            if not blocked and j < len(texts) and re.match(r"^[a-z]", texts[j]):
                out.append(join_unit(p, texts[j]))
                out.extend(skipped)
                i = j + 1
                continue
        out.append(p)
        i += 1
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
            if not r.get("cap_text"):
                by_page.setdefault(pno, []).append(r["link"])

    paras = [(k0, f"## {p}" if k0 in oracle.headings and not p.startswith("#") else p)
             for k0, p in paras]
    texts = mark_footnotes(paras, oracle)
    texts = merge_continuations(texts)
    texts = insert_region_links(texts, regions_by_page)
    texts = insert_images(texts, by_page, oracle)
    n_notes = sum(1 for p in texts if p.startswith("> **각주"))
    dropped += repeated_chars(doc)   # 지운 머리말·바닥글
    return "\n\n".join(texts) + "\n", {"dropped_chars": dropped,
                                       "figures": len(picks) + n_cropped,
                                       "footnotes": n_notes}
