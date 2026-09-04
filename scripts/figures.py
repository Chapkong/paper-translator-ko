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
MAX_HEIGHT_RATIO = 0.6   # 캡션 위쪽으로 이 비율을 넘게 자르지 않는다
MAX_BELOW_RATIO = 0.85   # 캡션 아래쪽 한계 — 전면 표는 페이지를 거의 채운다
BODY_LO, BODY_HI = 0.90, 1.12   # 본문 글자 크기로 인정하는 범위
WIDE_RATIO = 0.40  # 단 폭 대비 이 비율 이상이면 '넓은 줄'
PROSE_RUN = 3      # 본문으로 인정하려면 연속 몇 줄이어야 하는가
                   # (표 머리행이 본문 크기·폭이라 한두 줄로는 못 가른다)


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
    """수치·코드가 늘어선 표 행인가.

    `Miami-Ft. Lauderdale [12] 2.6 mil. 30.5% 1.01%`처럼 본문과 같은 크기·폭이라
    좌표만으로는 본문과 못 가른다. 스캔 텍스트는 셀이 한 스팬으로 합쳐져 나와
    줄 안 공백 간격도 쓸 수 없다(실측 전부 0). 남는 신호가 토큰 구성이다.
    """
    tokens = text.split()
    return sum(1 for t in tokens if _NUM_TOKEN.match(t)) >= 3


def _is_prose(line, body_size, col_w) -> bool:
    """본문 문단에 속한 줄인가.

    그림·표 내부 글자는 폰트 크기가 본문과 동떨어져 있다(실측 2.15~24.06pt vs 본문 8.31).
    본문 크기이면서 폭이 넓은 줄이라야 진짜 문단이다 — 'MC'처럼 짧은 조각은 그림의 일부다.
    수치가 늘어선 표 행은 크기·폭이 본문과 같아도 본문이 아니다.
    """
    return bool(body_size and body_size * BODY_LO <= line["size"] <= body_size * BODY_HI
                and (line["x1"] - line["x0"]) >= col_w * WIDE_RATIO
                and not _table_row(line["text"]))


def _region_top(cap, lines, body_size, col_x0, col_x1, page_height):
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
        if _is_prose(l, body_size, col_w):
            run += 1
            if run >= PROSE_RUN:
                break
        else:
            run = 0
            top = l["y0"] - 2
    return top


def _region_bottom(cap, lines, body_size, col_x0, col_x1, page_height):
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
        if _is_prose(l, body_size, col_w):
            run += 1
            if run >= PROSE_RUN:    # 본문 문단이 시작됐다
                break
        else:
            run = 0
            bottom = l.get("y1", l["y0"] + 8)
    return bottom


def plan(page, lines, body_size, pno) -> list:
    """이 페이지에서 잘라낼 영역을 정한다. 파일은 쓰지 않는다.

    반환 항목: {"page", "rect", "y", "link"} — link는 삽입할 마크다운이다.
    """
    width, height = page.rect.width, page.rect.height
    out = []

    try:
        tables = page.find_tables().tables
    except Exception:
        tables = []
    for t in tables:
        x0, y0, x1, y1 = t.bbox
        # 아래 여백은 최소로 — 표 캡션이 대개 바로 아래에 붙어 있다
        out.append({"page": pno, "rect": (x0 - PAD, y0 - PAD, x1 + PAD, y1 + 1), "y": y0})

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
                top = _region_top(cap, lines, body_size, col_x0, col_x1, height)
                if cap["y0"] - top >= MIN_HEIGHT:
                    rect = (col_x0 - FIG_PAD, top, col_x1 + FIG_PAD, cap["y0"] - 2)
                    break
            else:
                bottom = _region_bottom(cap, lines, body_size, col_x0, col_x1, height)
                if bottom - cap["y1"] >= MIN_HEIGHT:
                    rect = (col_x0 - FIG_PAD, cap["y1"] + 1, col_x1 + FIG_PAD, bottom + 2)
                    break
        if rect is None:                      # 어느 쪽에도 없다 — 자르지 않는다
            continue
        out.append({"page": pno, "rect": rect, "y": rect[1], "cap_text": cap["text"]})

    out.sort(key=lambda r: r["y"])
    for i, r in enumerate(out, 1):
        r["link"] = f"![](images/fig-p{pno + 1:03d}-{i:02d}.png)"
        r["name"] = f"fig-p{pno + 1:03d}-{i:02d}.png"
    return out


def covers(regions, line) -> bool:
    """이 줄이 잘라낼 영역 안에 있는가. 있으면 본문에서 뺀다."""
    cx, cy = (line["x0"] + line["x1"]) / 2, line["y0"]
    return any(x0 <= cx <= x1 and y0 <= cy <= y1 for x0, y0, x1, y1 in
               (r["rect"] for r in regions))


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
            if rect.is_empty or rect.height < MIN_HEIGHT:
                continue
            page.get_pixmap(clip=rect, dpi=DPI).save(img_dir / r["name"])
            n += 1
    return n
