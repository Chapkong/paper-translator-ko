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
MAX_HEIGHT_RATIO = 0.6   # 페이지 높이의 이 비율을 넘게 자르지 않는다
BODY_LO, BODY_HI = 0.90, 1.12   # 본문 글자 크기로 인정하는 범위
WIDE_RATIO = 0.40  # 단 폭 대비 이 비율 이상이면 '넓은 줄'


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


def _region_top(cap, lines, body_size, col_x0, col_x1, page_height):
    """캡션 위로 올라가며 본문 문단을 만나면 멈춘다.

    그림 내부 글자는 폰트 크기가 본문과 동떨어져 있다(실측 2.15~24.06pt vs 본문 8.31).
    본문 크기이면서 폭이 넓은 줄이라야 진짜 문단이다 — 'MC'처럼 짧은 조각은 그림의 일부다.
    """
    col_w = max(col_x1 - col_x0, 1.0)
    floor_y = max(cap["y0"] - page_height * MAX_HEIGHT_RATIO, 0.0)
    above = sorted((l for l in lines if l["y0"] < cap["y0"] - 2 and _overlaps(l, cap)),
                   key=lambda l: -l["y0"])
    top = cap["y0"]
    for l in above:
        if l["y0"] < floor_y:
            break
        is_body = (body_size and body_size * BODY_LO <= l["size"] <= body_size * BODY_HI
                   and (l["x1"] - l["x0"]) >= col_w * WIDE_RATIO)
        if is_body:
            break
        top = l["y0"] - 2
    return top


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
        top = _region_top(cap, lines, body_size, col_x0, col_x1, height)
        if cap["y0"] - top < MIN_HEIGHT:      # 그림이 없다 — 자르지 않는다
            continue
        out.append({"page": pno, "rect": (col_x0 - FIG_PAD, top, col_x1 + FIG_PAD, cap["y0"] - 2),
                    "y": top, "cap_text": cap["text"]})

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
