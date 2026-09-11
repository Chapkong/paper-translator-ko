#!/usr/bin/env python3
"""그림·표 영역을 찾아 페이지에서 잘라 이미지로 렌더링한다.

스캔본 PDF는 그림이 페이지 이미지의 일부라 따로 뽑을 수 없다. 그림 안 글자만
텍스트 레이어에 남아 본문을 오염시킨다(`p S2 ~~ ~ ~~~~~AC AC`). 영역을 통째로
렌더링해 넣으면 원문 모양이 살고 그 영역의 텍스트를 빼면 잔재도 함께 사라진다.

post.py가 줄 목록을 넘겨주고 결과 영역을 받아 쓴다. 여기서는 post를 부르지 않는다.
"""
import re

CAPTION_RE = re.compile(r"^(figure|table|그림|표)\s*\d+\s*[.:)]", re.I)

DPI = 200          # 렌더링 해상도
PAD = 4.0          # 표 bbox 여유
FIG_PAD = 14.0     # 그림 좌우 여유 — 도형이 본문 줄보다 바깥으로 나간다
GAP_PT = 15.0      # 캡션 위 빈 공간이 이만큼이면 진짜 캡션으로 본다
MIN_HEIGHT = 40.0  # 이보다 얇으면 그림이 없다고 본다
MATH_MIN = 0.30      # 줄에서 수학 폰트 비율이 이만큼 넘으면 수식 줄로 본다
EQ_WIDTH_MAX = 0.7   # 단 폭 대비 이보다 좁아야 독립 조판이다
EQ_MIN_HEIGHT = 8.0  # 수식은 한 줄이라 그림 기준(MIN_HEIGHT)으로는 다 버려진다
EQ_MIN_CHARS = 6     # 공백 뺀 글자 수. 이보다 짧으면 수식이 아니라 조각이다
EQ_DOMINANT = 0.5    # 영역 안 글자 중 수학 폰트 비율이 이만큼 넘으면 수식 영역이다
MAX_HEIGHT_RATIO = 0.6   # 캡션 위쪽으로 이 비율을 넘게 자르지 않는다
MAX_BELOW_RATIO = 0.85   # 캡션 아래쪽 한계 — 전면 표는 페이지를 거의 채운다
MAX_GRAPHIC_RATIO = 0.60 # 페이지 면적의 이 비율을 넘는 도형·이미지는 전면 배경으로 본다
BODY_LO, BODY_HI = 0.90, 1.12   # 본문 글자 크기로 인정하는 기본 범위
COMMON_SIZE_RATIO = 0.20        # 전체 줄의 이 비율 이상을 차지하는 크기는 본문으로 인정한다
COMMON_SIZE_MAX = 1.20          # 다만 중앙값의 이 배를 넘으면 제목이다 — 넓히지 않는다
GROW_GAP = 40.0    # 그림 글자 덩어리를 키울 때 이만큼 떨어진 것까지 같은 그림으로 본다
WIDE_RATIO = 0.40  # 단 폭 대비 이 비율 이상이면 '넓은 줄'
PROSE_RUN = 3      # 본문으로 인정하려면 연속 몇 줄이어야 하는가
                   # (표 머리행이 본문 크기·폭이라 한두 줄로는 못 가른다)


def body_band(sizes, body_size):
    """본문으로 인정할 글자 크기 범위 (lo, hi).

    기본은 중앙값의 0.90~1.12배다. 그런데 텍스트 레이어가 크기를 정수로 양자화한
    스캔본은 본문이 두 값으로 갈린다(Teece 실측: 8pt 52%, 9pt 35%). 중앙값 8.0에
    대해 9.0은 1.125배라 기본 범위 밖으로 밀려 본문의 35.8%가 그림으로 오판되고,
    그 결과 그림 영역이 본문 한가운데서 끊긴다.

    임계값을 뭉뚱그려 넓히면 표 행이 본문으로 읽혀 반대쪽이 깨진다(Noda·Bower 실측
    잘린 문단 0.016 → 0.024). 대신 문서가 실제로 많이 쓰는 크기만 본문으로 인정한다.
    크기가 연속값인 문서는 최빈 크기가 14%에 그쳐 범위가 그대로 유지된다.
    """
    lo, hi = body_size * BODY_LO, body_size * BODY_HI
    if not sizes or not body_size:
        return lo, hi
    counts = {}
    for v in sizes:
        counts[round(v, 1)] = counts.get(round(v, 1), 0) + 1
    total = sum(counts.values())
    ceiling = body_size * COMMON_SIZE_MAX
    for size, n in counts.items():
        if n < total * COMMON_SIZE_RATIO:
            continue
        if lo <= size <= ceiling:
            hi = max(hi, size + 0.05)          # 반올림 폭만큼 여유를 준다
        elif body_size * 0.80 <= size < lo:
            lo = min(lo, size - 0.05)
    return lo, hi


def _overlaps(a, b, slack=30.0):
    return not (a["x1"] < b["x0"] - slack or a["x0"] > b["x1"] + slack)


def _column_bounds(lines, cap, width):
    """캡션이 속한 단의 좌우 경계. 두 단에 걸친 캡션이면 페이지 전체."""
    if (cap["x1"] - cap["x0"]) > 0.6 * width:
        peers = lines
    else:
        mid = width / 2
        left = (cap["x0"] + cap["x1"]) / 2 < mid
        peers = [l for l in lines if ((l["x0"] + l["x1"]) / 2 < mid) == left] or lines
    return min(l["x0"] for l in peers), max(l["x1"] for l in peers)


def is_caption(cap, lines, body_size, width) -> bool:
    """캡션처럼 보이는 줄인가.

    본문 속 `Figure 2.) Increased production by additional` 같은 오탐을 걸러야 한다.
    실측상 진짜 캡션은 셋 중 하나를 만족한다 — 글자가 본문보다 작거나(7.6·7.8pt),
    위에 빈 공간이 있거나(34pt), 단 안에서 가운데로 밀려 있다(x0 163, 기준선 45).
    """
    if not CAPTION_RE.match(cap["text"].strip()):
        return False
    x0, x1 = _column_bounds(lines, cap, width)
    col_w = x1 - x0
    small = bool(body_size and cap["size"] <= body_size * 0.95)
    above = [l for l in lines if l["y0"] < cap["y0"] - 2 and _overlaps(l, cap)]
    gap = (cap["y0"] - max(l["y0"] for l in above)) >= GAP_PT if above else True
    centered = col_w > 0 and (cap["x0"] - x0) >= col_w * 0.15
    return small or gap or centered


_NUM_TOKEN = re.compile(r"^[\d.,%$/\[\]()·~-]+$")


def _table_row(text: str) -> bool:
    """수치·코드가 늘어선 표 행이거나 그림 칸 글자인가.

    `Miami-Ft. Lauderdale [12] 2.6 mil. 30.5% 1.01%`처럼 본문과 같은 크기·폭이라
    좌표만으로는 본문과 못 가른다. 스캔 텍스트는 셀이 한 스팬으로 합쳐져 나와
    줄 안 공백 간격도 쓸 수 없다(실측 전부 0). 남는 신호가 토큰 구성이다.

    프로세스 그림의 매트릭스 칸은 수치가 적은 대신 칸마다 글머리표가 붙는다
    (`* "Cellular went very * More confidence in * Articulation of`). 이 신호가
    없으면 매트릭스 행이 본문으로 읽혀 영역이 아래쪽 일부만 잘린다(실측 p19 116pt).
    """
    if text.count("*") >= 2 or "|" in text:
        return True
    tokens = text.split()
    return sum(1 for t in tokens if _NUM_TOKEN.match(t)) >= 3


def _is_prose(line, band, col_w) -> bool:
    """본문 문단에 속한 줄인가.

    그림·표 내부 글자는 폰트 크기가 본문과 동떨어져 있다(실측 2.15~24.06pt vs 본문 8.31).
    본문 크기이면서 폭이 넓은 줄이라야 진짜 문단이다 — 'MC'처럼 짧은 조각은 그림의 일부다.
    수치가 늘어선 표 행은 크기·폭이 본문과 같아도 본문이 아니다.
    """
    return bool(band[1] and band[0] <= line["size"] <= band[1]
                and (line["x1"] - line["x0"]) >= col_w * WIDE_RATIO
                and not _table_row(line["text"]))


def _region_top(cap, lines, band, col_x0, col_x1, page_height):
    """캡션 위로 올라가며 본문 문단을 만나면 멈춘다. 그림 캡션은 그림 아래에 붙는다."""
    col_w = max(col_x1 - col_x0, 1.0)
    floor_y = max(cap["y0"] - page_height * MAX_HEIGHT_RATIO, 0.0)
    above = sorted((l for l in lines if l["y0"] < cap["y0"] - 2 and _overlaps(l, cap)),
                   key=lambda l: -l["y0"])
    # 본문은 여러 줄이 이어진다. 한 줄만 보고 멈추면 표의 긴 행 하나에 걸려
    # 영역이 잘린다. 연속 두 줄이 본문처럼 보일 때만 멈춘다.
    top, run = cap["y0"], 0
    for l in above:
        if l["y0"] < floor_y:
            break
        if _is_prose(l, band, col_w):
            run += 1
            if run >= PROSE_RUN:
                break
        else:
            run = 0
            top = l["y0"] - 2
    return top


def _region_bottom(cap, lines, band, col_x0, col_x1, page_height):
    """캡션 아래로 내려가며 본문 문단을 만나면 멈춘다.

    **표 캡션은 표 위에 붙는다.** 그림과 반대다. 이 방향을 보지 않으면 괘선 없는 표가
    통째로 본문에 흘러들어 문단의 절반이 문장 중간에서 끊긴다(Noda·Bower 논문 실측 0.46).
    """
    col_w = max(col_x1 - col_x0, 1.0)
    ceil_y = min(cap["y1"] + page_height * MAX_BELOW_RATIO, page_height)
    below = sorted((l for l in lines if l["y0"] > cap["y1"] + 1 and _overlaps(l, cap)),
                   key=lambda l: l["y0"])
    bottom, run = cap["y1"], 0
    for l in below:
        if l["y0"] > ceil_y:
            break
        if _is_prose(l, band, col_w):
            run += 1
            if run >= PROSE_RUN:    # 본문 문단이 시작됐다
                break
        else:
            run = 0
            bottom = l.get("y1", l["y0"] + 8)
    return bottom


def _inside(rect, line) -> bool:
    cx, cy = (line["x0"] + line["x1"]) / 2, line["y0"]
    return rect[0] <= cx <= rect[2] and rect[1] <= cy <= rect[3]


def _ink_bbox(page, rect):
    """영역에 세로로 걸치는 도형·이미지를 합친 실제 잉크 범위. 없으면 None.

    전면 스캔 배경은 그림이 아니라 페이지 그 자체다. 면적으로 걸러내지 않으면
    스캔본에서 영역이 페이지 전체로 부풀어 본문을 통째로 삼킨다.
    """
    page_area = max(page.rect.width * page.rect.height, 1.0)
    y0, y1 = rect[1], rect[3]
    boxes = []
    try:
        boxes += [tuple(d["rect"]) for d in page.get_drawings() if d.get("rect")]
    except Exception:
        pass
    try:
        boxes += [tuple(b["bbox"]) for b in page.get_text("dict").get("blocks", [])
                  if b.get("type") == 1]
    except Exception:
        pass
    hit = []
    for bx0, by0, bx1, by1 in boxes:
        if bx1 <= bx0 or by1 <= by0:
            continue
        if (bx1 - bx0) * (by1 - by0) > page_area * MAX_GRAPHIC_RATIO:
            continue                                  # 전면 배경 — 그림이 아니다
        if by1 <= y0 or by0 >= y1:
            continue                                  # 영역과 세로로 안 겹친다
        hit.append((bx0, by0, bx1, by1))
    if not hit:
        return None
    return (min(b[0] for b in hit), min(b[1] for b in hit),
            max(b[2] for b in hit), max(b[3] for b in hit))


def _figure_extent(rect, lines, band):
    """영역의 y밴드 안에서 그림에 속한 글자들이 차지하는 좌우 범위 (x0, x1). 없으면 None.

    스캔본은 그림이 페이지 이미지의 일부라 도형 좌표가 없다(Teece p17 실측:
    get_drawings 0개, 유일한 이미지는 전면 스캔이라 배경으로 걸러진다). 그때 남는
    신호가 그림 안 글자다 — 본문보다 작고 좁아 _is_prose가 이미 본문에서 걸러낸 것들이다.

    멀리 떨어진 글자는 같은 그림이 아니다. 현재 범위에서 GROW_GAP 안에 닿는 것만
    차례로 흡수해 그림 하나의 덩어리를 키운다.
    """
    col_w = max(rect[2] - rect[0], 1.0)
    cand = [l for l in lines if rect[1] <= l["y0"] <= rect[3]
            and not _is_prose(l, band, col_w)]
    if not cand:
        return None
    x0, x1, growing = rect[0], rect[2], True
    while growing:
        growing = False
        for l in cand:
            if l["x1"] < x0 - GROW_GAP or l["x0"] > x1 + GROW_GAP:
                continue                       # 너무 멀다 — 같은 그림이 아니다
            if l["x0"] < x0 or l["x1"] > x1:
                x0, x1, growing = min(x0, l["x0"]), max(x1, l["x1"]), True
    return (x0, x1)


def _expanded(rect, page, lines, band):
    """캡션 단으로 잡은 영역을 그림 실물 크기까지 넓힌다.

    전면 다이어그램의 캡션은 그림보다 좁게 가운데 놓인다. 캡션이 속한 단으로 폭을
    정하면 그림의 반대쪽 절반이 본문으로 샌다(Teece p17 실측: 크롭 x38~377,
    그림 라벨 x332~455 — 오른쪽 절반이 문장 한가운데로 유입됐다).

    실물 범위는 두 곳에서 읽는다. 벡터 조판이면 도형 좌표에서, 스캔본이면 그림 안
    글자에서. 넓힌 결과가 본문 문단을 삼키면 넓히지 않는다 — 반대 방향 손상이 더 나쁘다.
    """
    wide = rect
    ink = _ink_bbox(page, rect)
    if ink is not None:
        wide = (min(wide[0], ink[0] - FIG_PAD), min(wide[1], ink[1] - 2),
                max(wide[2], ink[2] + FIG_PAD), max(wide[3], ink[3] + 2))
    span = _figure_extent(rect, lines, band)
    if span is not None:                       # 글자는 좌우만 알려준다. 세로는 이미
        wide = (min(wide[0], span[0] - FIG_PAD), wide[1],   # 본문 경계로 정해져 있고,
                max(wide[2], span[1] + FIG_PAD), wide[3])   # 여기 여백을 더하면 캡션을 삼킨다
    wide = (max(wide[0], 0.0), max(wide[1], 0.0),
            min(wide[2], page.rect.width), min(wide[3], page.rect.height))
    if wide == rect:
        return rect
    col_w = max(rect[2] - rect[0], 1.0)
    for l in lines:
        if _is_prose(l, band, col_w) and _inside(wide, l) and not _inside(rect, l):
            return rect
    return wide


def plan(page, lines, body_size, pno, band=None) -> list:
    """이 페이지에서 잘라낼 영역을 정한다. 파일은 쓰지 않는다.

    band는 본문으로 인정할 글자 크기 범위다. 문서 전체 분포에서 구해야 정확하므로
    post.ordered_lines가 body_band()로 구해 넘긴다. 없으면 중앙값에서 기본 범위를 쓴다.

    반환 항목: {"page", "rect", "y", "link"} — link는 삽입할 마크다운이다.
    """
    if band is None:
        band = (body_size * BODY_LO, body_size * BODY_HI)
    width, height = page.rect.width, page.rect.height
    out = []

    try:
        tables = page.find_tables().tables
    except Exception:
        tables = []
    for t in tables:
        x0, y0, x1, y1 = t.bbox
        # 아래 여백은 최소로 — 표 캡션이 대개 바로 아래에 붙어 있다
        rect = (x0 - PAD, y0 - PAD, x1 + PAD, y1 + 1)
        region = {"page": pno, "rect": rect, "y": y0}
        if _math_dominant(lines, rect):
            # 표가 아니라 2차원으로 조판된 수식이다. 제자리에 이미지로 놓는다
            region["kind"] = "equation"
            region["after_text"] = _anchor_above(lines, rect, width)
        out.append(region)

    for cap in lines:
        if not is_caption(cap, lines, body_size, width):
            continue
        col_x0, col_x1 = _column_bounds(lines, cap, width)
        # 표 캡션은 표 위에, 그림 캡션은 그림 아래에 붙는다. 먼저 제 방향을 보고,
        # 비어 있으면 반대쪽을 본다(저널마다 관행이 갈린다).
        is_table_cap = bool(re.match(r"^(table|표)\b", cap["text"].strip(), re.I))
        order = ["below", "above"] if is_table_cap else ["above", "below"]
        rect = None
        for direction in order:
            if direction == "above":
                top = _region_top(cap, lines, band, col_x0, col_x1, height)
                if cap["y0"] - top >= MIN_HEIGHT:
                    rect = (col_x0 - FIG_PAD, top, col_x1 + FIG_PAD, cap["y0"] - 2)
                    break
            else:
                bottom = _region_bottom(cap, lines, band, col_x0, col_x1, height)
                if bottom - cap["y1"] >= MIN_HEIGHT:
                    rect = (col_x0 - FIG_PAD, cap["y1"] + 1, col_x1 + FIG_PAD, bottom + 2)
                    break
        if rect is None:                      # 어느 쪽에도 없다 — 자르지 않는다
            continue
        rect = _expanded(rect, page, lines, band)
        out.append({"page": pno, "rect": rect, "y": rect[1], "cap_text": cap["text"]})

    out.extend(_equation_regions(lines, width, pno, out))
    out.sort(key=lambda r: r["y"])
    for i, r in enumerate(out, 1):
        pre = "eq" if r.get("kind") == "equation" else "fig"
        r["name"] = f"{pre}-p{pno + 1:03d}-{i:02d}.png"
        r["link"] = f"![](images/{r['name']})"
    return out


def is_display_equation(line, col_x0, col_x1) -> bool:
    """독립 줄로 조판된 수식인가.

    필수 신호는 수학 폰트 비율이다. 이것이 없으면 수식으로 보지 않는다 — 본문을
    이미지로 삼키면 번역이 불가능해지고 보존율 분모가 왜곡된다.
    보조로 줄 폭을 본다. 단 폭을 채운 줄은 인라인 수식이 든 본문이다.
    """
    if line.get("math", 0.0) < MATH_MIN:
        return False
    col_width = col_x1 - col_x0
    if col_width <= 0:
        return False
    return (line["x1"] - line["x0"]) < col_width * EQ_WIDTH_MAX


_EQ_OP = re.compile(r"[=≈≤≥∑∏∫→←⇒∂±×÷∼≡]")
_EQ_NUM = re.compile(r"\(\d{1,2}\)\s*$")


def _is_substantial(texts) -> bool:
    """수식 영역으로 남길 만한 덩어리인가.

    수학 폰트만 보면 마침표 하나까지 수식이 된다(When Does 실측: math>=0.3인 줄
    115개 중 88개가 6자 미만 조각). 조각까지 잘라내면 영역이 51개로 불어나
    본문에서 글자가 빠지고 잘린 문단 비율이 0.071 → 0.089로 나빠졌다.
    연산자나 수식 번호가 있어야 수식으로 본다.
    """
    joined = " ".join(texts)
    if len(re.sub(r"\s", "", joined)) < EQ_MIN_CHARS:
        return False
    return bool(_EQ_OP.search(joined) or _EQ_NUM.search(joined))


def _anchor_above(lines, rect, width, skip_ids=()) -> str:
    """영역 바로 위, 같은 단에 있는 줄의 텍스트. 없으면 빈 문자열.

    수식에는 캡션이 없어 캡션 앵커를 쓸 수 없다. 바로 위 줄을 남겨 두면 문단
    조립이 끝난 뒤 그 문단 뒤에 이미지를 놓을 수 있다.

    가로 겹침을 요구하면 안 된다 — 수식은 가운데나 오른쪽으로 밀려 조판되는데
    도입 문장은 그보다 왼쪽에서 끝난다(Yin 2026 실측: 영역 x 280~354, 도입 문장
    x 72~267). 겹침으로 걸러 도입 문장이 탈락하자 이미지가 다른 문단 뒤로 갔다.
    대신 같은 단인지를 본다 — 2단 조판에서 옆 단 줄을 집으면 안 되기 때문이다.
    """
    if not lines:
        return ""
    col_x0, col_x1 = _column_bounds(lines, {"x0": rect[0], "x1": rect[2]}, width)
    above = [l for l in lines if id(l) not in skip_ids and l["y1"] <= rect[1] + 1
             and col_x0 - 2 <= (l["x0"] + l["x1"]) / 2 <= col_x1 + 2]
    return max(above, key=lambda l: l["y1"])["text"] if above else ""


def _math_dominant(lines, rect) -> bool:
    """이 영역 안이 수식인가. 표 탐지가 선점한 수식 조판을 되돌리는 판정.

    Yin(2026)의 큰 ∑는 2차원으로 조판돼 `xn =`, `B`, `X`, `b=1` 같은 조각으로
    흩어진다. pymupdf의 find_tables가 이 격자를 표로 먼저 claim하는 바람에
    수식 탐지가 닿지 못했다 — 문서 전체에서 수식 영역이 2개만 잡혔고, 문단은
    `…be formulated as`에서 끊긴 채 이미지도 놓이지 않았다.
    """
    inside = [l for l in lines if _inside(rect, l)]
    total = sum(len(l["text"]) for l in inside)
    if not total:
        return False
    math = sum(len(l["text"]) * l.get("math", 0.0) for l in inside)
    return (math / total >= EQ_DOMINANT
            and _is_substantial([l["text"] for l in inside]))


def _equation_regions(lines, width, pno, existing) -> list:
    """독립 수식 줄을 영역으로 묶는다. 캡션이 없으므로 바로 위 본문 줄을 앵커로 남긴다.

    수식이 본문에 뭉개진 글자로 섞이거나(When Does: `A˙ = θ Sη Aφ0+φ1E f t. (6)`)
    아예 누락되면(Yin) 문단이 그 자리에서 끊긴다. 이미지로 옮기면 사람이 읽을 수
    있고, quality.checked_paragraphs()가 이미지 다음 문단을 절단 검사에서 빼준다.
    """
    eqs = [l for l in lines
           if not covers(existing, l)
           and is_display_equation(l, *_column_bounds(lines, l, width))]
    if not eqs:
        return []
    eq_ids = {id(l) for l in eqs}
    eqs.sort(key=lambda l: l["y0"])

    groups, cur = [], [eqs[0]]
    for l in eqs[1:]:
        prev = cur[-1]
        if l["y0"] - prev["y1"] <= max(6.0, 1.6 * (prev["y1"] - prev["y0"])):
            cur.append(l)
        else:
            groups.append(cur)
            cur = [l]
    groups.append(cur)
    groups = [g for g in groups if _is_substantial([l["text"] for l in g])]

    out = []
    for g in groups:
        x0, x1 = min(l["x0"] for l in g), max(l["x1"] for l in g)
        y0, y1 = min(l["y0"] for l in g), max(l["y1"] for l in g)
        rect = (x0 - FIG_PAD, y0 - PAD, x1 + FIG_PAD, y1 + PAD)
        out.append({"page": pno, "y": y0, "kind": "equation", "rect": rect,
                    "after_text": _anchor_above(lines, rect, width, eq_ids)})
    return out


def covers(regions, line) -> bool:
    """이 줄이 잘라낼 영역 안에 있는가. 있으면 본문에서 뺀다."""
    return any(_inside(r["rect"], line) for r in regions)


def render(doc, regions_by_page: dict, img_dir) -> int:
    """정해진 영역을 PNG로 저장한다. 저장한 개수를 돌려준다."""
    import pymupdf

    if not regions_by_page:
        return 0
    img_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for pno, regions in regions_by_page.items():
        page = doc[pno]
        for r in regions:
            rect = pymupdf.Rect(*r["rect"]) & page.rect
            floor = EQ_MIN_HEIGHT if r.get("kind") == "equation" else MIN_HEIGHT
            if rect.is_empty or rect.height < floor:
                continue
            page.get_pixmap(clip=rect, dpi=DPI).save(img_dir / r["name"])
            n += 1
    return n
