#!/usr/bin/env python3
"""의존성 없는 자체 테스트.

사용법:
    python scripts/selftest.py            # 전체 실행
    python scripts/selftest.py 이름 이름   # 지정한 테스트만 실행
"""
import sys, traceback
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

TESTS = {}


def test(fn):
    TESTS[fn.__name__] = fn
    return fn


FIXTURE = ROOT / "work" / "_fixture" / "fixture.pdf"

# 픽스처 본문 — 후처리 결과가 이 문장들과 정확히 일치해야 한다.
# 실제 논문처럼 문단 첫 줄을 들여써서 PyMuPDF 블록이 문단 단위로 갈리게 한다.
P1_HEAD = ["INTRODUCTION"]
P1_PARA1 = ["The model is developed in this",
            "section. Firms rely on communi-",
            "cation among their units."]
P1_PARA2 = ["A second paragraph starts here",
            "and ends on this line."]
P1_RIGHT = ["This right column follows the",
            "left one in reading order."]
P2_LEFT = ["Heterogeneity is the first",
           "condition of the model."]
P2_RIGHT = ["Rents are bound to the firm",
            "under imperfect mobility."]
P2_NOTE = ["1 See Nelson (1991) for a",
           "discussion of firm capabilities."]
P3_LEFT = ["The final section applies the",
           "model to strategy formulation."]
P3_RIGHT = ["Implications for research are",
            "discussed at the end."]


def _draw(page, x0, y0, lines, size, indent=0):
    """줄바꿈 위치를 우리가 정하기 위해 한 줄씩 직접 찍는다.

    indent를 주면 첫 줄만 들여쓴다 — 실제 논문의 문단 첫 줄과 같고,
    PyMuPDF가 이 지점에서 블록을 나눈다.
    """
    for i, line in enumerate(lines):
        x = x0 + (indent if i == 0 else 0)
        page.insert_text((x, y0 + i * (size + 3)), line, fontsize=size, fontname="helv")


def build_fixture() -> Path:
    """2단 본문 + 각주 + 러닝헤드 + 반복 푸터 + 그림/로고가 든 3쪽 PDF를 만든다."""
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    body = [(None, P1_RIGHT), (P2_LEFT, P2_RIGHT), (P3_LEFT, P3_RIGHT)]
    for pno, (left, right) in enumerate(body):
        page = doc.new_page(width=530, height=800)
        _draw(page, 48, 45, [f"{180 + pno} A. Author"], 9.8)      # 러닝헤드
        if pno == 0:                                               # 제목 + 문단 2개
            _draw(page, 48, 80, P1_HEAD, 9.5)
            _draw(page, 48, 105, P1_PARA1, 8.0, indent=8)
            _draw(page, 48, 145, P1_PARA2, 8.0, indent=8)
        else:
            _draw(page, 48, 80, left, 8.0, indent=8)
        _draw(page, 285, 80, right, 8.0, indent=8)
        if pno == 1:
            _draw(page, 285, 620, P2_NOTE, 6.5)                    # 각주
        _draw(page, 120, 750, ["This content downloaded on Tue, 01 Sep 2026"], 8.0)
    page = doc[2]                                                   # 그림 영역 + 캡션
    page.draw_rect(pymupdf.Rect(70, 480, 250, 600), width=1.2)      # 도형
    _draw(page, 120, 520, ["Panel A Panel B"], 14.0)                # 도형 안 잔재(본문과 다른 크기)
    _draw(page, 90, 620, ["Figure 1. A sample diagram"], 6.5)       # 캡션(본문보다 작다)
    page = doc[2]                                                   # 그림 7% + 로고 0.4%
    fig = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 150))
    fig.set_rect(fig.irect, (30, 90, 200))
    page.insert_image(pymupdf.Rect(60, 300, 260, 450), pixmap=fig)
    logo = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 40))
    logo.set_rect(logo.irect, (200, 30, 30))
    page.insert_image(pymupdf.Rect(300, 300, 340, 340), pixmap=logo)
    doc.save(FIXTURE)
    doc.close()
    return FIXTURE


@test
def fixture_builds():
    p = build_fixture()
    doc = pymupdf.open(p)
    assert doc.page_count == 3, doc.page_count
    text = doc[0].get_text()
    assert "INTRODUCTION" in text
    assert "communi-" in text, "하이픈 분철이 픽스처에 들어가야 한다"
    doc.close()


@test
def kordoc_adapter_degrades_gracefully():
    import kordoc
    assert kordoc.to_markdown(ROOT / "input" / "없는파일.pdf") is None, \
        "실패 시 예외가 아니라 None이어야 폴백할 수 있다"
    if kordoc.available():          # CLI가 있는 환경에서만 본 검증
        md = kordoc.to_markdown(build_fixture())
        assert md and "INTRODUCTION" in md, (md or "")[:200]
    else:
        print("     (kordoc CLI 없음 — 폴백 경로만 검증)")


@test
def oracle_knows_paragraph_starts_and_sizes():
    from post import build_oracle, key
    doc = pymupdf.open(build_fixture())
    o = build_oracle(doc)
    assert key("The model is developed in this") in o.starts, "블록 첫 줄은 문단 시작이다"
    assert key("section. Firms rely on communi-") not in o.starts, "이어지는 줄은 문단 시작이 아니다"
    assert 7.5 < o.body_size < 8.5, o.body_size
    assert o.sizes[key("1 See Nelson (1991) for a")] < o.body_size * 0.85, "각주는 작은 폰트다"
    assert o.page_last[2], "페이지별 마지막 줄이 있어야 이미지를 그 자리에 넣는다"
    doc.close()


@test
def paragraphs_and_hyphens_are_rebuilt():
    from post import rebuild_paragraphs, join_unit, Oracle, key
    o = Oracle(starts={key("The model is developed in this"), key("Rents are bound to the firm")},
               sizes={}, body_size=8.0)
    md = ("The model is developed in this\n\nsection. Firms rely on communi-\n\n"
          "cation among their units.\n\nRents are bound to the firm\n\nunder imperfect mobility.")
    paras = rebuild_paragraphs(md, o)
    assert [p[1] for p in paras] == [
        "The model is developed in this section. Firms rely on communication among their units.",
        "Rents are bound to the firm under imperfect mobility."], paras
    assert paras[0][0] == key("The model is developed in this"), "문단은 첫 줄 키를 들고 다녀야 한다"
    assert join_unit("ends with communi-", "cation") == "ends with communication"
    assert join_unit("ends with word", "next") == "ends with word next"
    assert join_unit("", "first") == "first"


@test
def footnotes_marked_and_cover_dropped():
    from post import mark_footnotes, drop_cover, is_footnote, Oracle, key
    kn, kb = key("1 See Nelson (1991) for a"), key("Rents are bound to the firm")
    o = Oracle(starts=set(), sizes={kn: 6.5, kb: 8.0}, body_size=8.0)
    paras = [(kb, "Rents are bound to the firm under imperfect mobility."),
             (kn, "1 See Nelson (1991) for a discussion of firm capabilities."),
             ("모르는키", "폰트를 모르는 문단은 본문으로 둔다.")]
    out = mark_footnotes(paras, o)
    assert out[0] == "Rents are bound to the firm under imperfect mobility."
    assert out[1] == "> **각주 1** See Nelson (1991) for a discussion of firm capabilities.", out[1]
    assert not out[2].startswith(">"), "모르는 문단을 각주로 오판하면 안 된다"
    assert is_footnote(kn, o) and not is_footnote(kb, o)

    kept, dropped = drop_cover([("k1", "The Cornerstones of Competitive Advantage"),
                                ("k2", "JSTOR is a not-for-profit service that helps scholars."),
                                ("k3", "All use subject to https://about.jstor.org/terms"),
                                ("k4", "본문 시작.")])
    assert [p[1] for p in kept] == ["The Cornerstones of Competitive Advantage", "본문 시작."], kept
    assert dropped > 0


@test
def only_real_figures_are_kept():
    import shutil
    from post import (pick_images, save_images, strip_kordoc_images,
                      insert_images, build_oracle, key)
    doc = pymupdf.open(build_fixture())
    picks = pick_images(doc)
    assert len(picks) == 1, f"그림 1개만 남아야 한다(로고 제외): {picks}"
    assert picks[0][0] == 2, "3쪽의 그림이어야 한다"
    out = ROOT / "work" / "_fixture" / "images"
    if out.exists():
        shutil.rmtree(out)
    by_page = save_images(doc, picks, out, "fixture")
    files = list(out.glob("*"))
    assert len(files) == 1 and " " not in files[0].name, files
    assert by_page[2][0].startswith("![](images/")

    o = build_oracle(doc)
    # 페이지 마지막 줄은 바닥글이 아니라 본문이어야 이미지가 제자리에 들어간다
    assert o.page_last[2], "페이지 마지막 문단 기준이 있어야 이미지를 그 자리에 넣는다"
    paras = insert_images(["The final section applies the model to strategy formulation.",
                           "Implications for research are discussed at the end."], by_page, o)
    assert paras[-1].startswith("![](images/"), paras
    assert strip_kordoc_images("본문\n\n![image](image_001.png)\n\n다음") == "본문\n\n다음"
    doc.close()


WIDE = ROOT / "work" / "_fixture" / "wide.pdf"

# 인용 블록 — 단 기준선보다 14pt 안팎 들여쓰되, 스캔본처럼 줄마다 x0가 흔들린다.
# 실측 근거: Teece p29 Porter 인용문의 x0가 65.4~69.0으로 3.6pt 요동쳤다.
Q_LEFT = ["Strategic fit among many activities is",
          "fundamental not only to competitive",
          "advantage but also to sustainability"]
Q_LEFT_X = [62.0, 64.5, 61.5]        # 왼쪽 단 기준선 48 대비 +14.0 / +16.5 / +13.5
Q_RIGHT = ["of that advantage. It is harder for",
           "a rival to match an array of activities."]
Q_RIGHT_X = [299.5, 301.0]           # 오른쪽 단 기준선 285 대비 +14.5 / +16.0

# 전면 다이어그램 — 두 단에 걸치는데 캡션은 가운데 짧게 놓인다(Teece Figure 2와 같은 꼴).
WIDE_LABEL_RIGHT = "Seizing Capability"
WIDE_CAPTION = "Figure 1. A wide two-column diagram"


def build_wide_fixture() -> Path:
    """단을 넘어가는 인용 블록(1쪽)과 전면 다이어그램(2쪽)이 든 PDF."""
    WIDE.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()

    page = doc.new_page(width=530, height=800)          # 1쪽 — 인용 블록
    _draw(page, 48, 45, ["182 A. Author"], 9.8)
    _draw(page, 48, 80, ["Porter states the point directly in his",
                         "discussion of activity systems, which",
                         "runs as follows."], 8.0, indent=8)
    for i, (x, line) in enumerate(zip(Q_LEFT_X, Q_LEFT)):
        _draw(page, x, 130 + i * 11, [line], 8.0)
    for i, (x, line) in enumerate(zip(Q_RIGHT_X, Q_RIGHT)):
        _draw(page, x, 80 + i * 11, [line], 8.0)
    _draw(page, 285, 115, ["The argument resumes in this column",
                           "after the quotation ends."], 8.0, indent=8)

    page = doc.new_page(width=530, height=800)          # 2쪽 — 전면 다이어그램
    _draw(page, 48, 45, ["183 A. Author"], 9.8)
    _draw(page, 48, 80, ["The framework is summarized below",
                         "in a single diagram that spans the",
                         "full width of the printed page."], 8.0, indent=8)
    _draw(page, 285, 80, ["The right column carries its own",
                          "body text alongside the left one.",
                          "Both columns run the whole page."], 8.0, indent=8)
    page.draw_rect(pymupdf.Rect(60, 400, 470, 530), width=1.2)   # 두 단을 가로지르는 도형
    _draw(page, 140, 440, ["Sensing Opportunities"], 7.0)        # 왼쪽 절반 라벨
    _draw(page, 310, 440, [WIDE_LABEL_RIGHT], 7.0)               # 오른쪽 절반 라벨
    _draw(page, 310, 470, ["Managing Threats"], 7.0)
    _draw(page, 150, 550, [WIDE_CAPTION], 6.5)                   # 좁고 가운데 놓인 캡션

    page = doc.new_page(width=530, height=800)          # 3쪽 — 스캔본 꼴(도형 좌표가 없다)
    _draw(page, 48, 45, ["184 A. Author"], 9.8)
    _draw(page, 48, 80, ["A scanned page keeps the diagram",
                         "inside the page image, so no vector",
                         "coordinates survive for it."], 8.0, indent=8)
    _draw(page, 285, 80, ["Only the text layer remains, and the",
                          "labels inside the diagram sit in it",
                          "alongside the body of the article."], 8.0, indent=8)
    _draw(page, 140, 440, ["Sensing Opportunities"], 7.0)        # 도형 없이 라벨만
    _draw(page, 310, 440, [WIDE_LABEL_RIGHT], 7.0)
    _draw(page, 310, 470, ["Managing Threats"], 7.0)
    _draw(page, 150, 550, [WIDE_CAPTION], 6.5)
    doc.save(WIDE)
    doc.close()
    return WIDE


@test
def quote_block_survives_jitter_and_column_break():
    """인용 블록은 x0가 흔들려도, 단을 넘어가도 한 문단으로 이어져야 한다.

    Teece 2007에서 이 두 가지가 깨져 인용문이 줄마다 쪼개졌고 단어 한가운데가
    갈라졌다(`…change manage` / `ment. Although…`). 잘린 문단 비율 0.131의 절반이 여기서 나왔다.
    """
    from post import build_oracle, key
    doc = pymupdf.open(build_wide_fixture())
    o = build_oracle(doc)
    keys = [k for k, _ in o.seq]
    starts = [s for _, s in o.seq]

    def at(text):
        return starts[keys.index(key(text))]

    assert at(Q_LEFT[0]), "인용문 첫 줄은 문단을 열어야 한다"
    for n, line in enumerate(Q_LEFT[1:], 2):
        assert not at(line), f"지터 때문에 인용문 {n}번째 줄이 새 문단을 열었다"
    for n, line in enumerate(Q_RIGHT, 1):
        assert not at(line), f"단 경계를 넘자 인용문 {n}번째 줄이 새 문단을 열었다"
    doc.close()


@test
def wide_figure_region_covers_whole_diagram():
    """전면 다이어그램은 캡션이 좁아도 전체가 잘려야 한다.

    캡션이 속한 단으로 폭을 정하면 그림의 반대쪽 절반이 본문으로 샌다.
    Teece p17 실측: 크롭 x 38~377, 라벨 실제 x 332~455 — 오른쪽 절반이 본문에 유입됐다.
    """
    import figures
    from post import page_lines, build_oracle
    doc = pymupdf.open(build_wide_fixture())
    body = build_oracle(doc).body_size
    # 2쪽은 도형 좌표가 있는 조판, 3쪽은 도형이 없는 스캔본 꼴 — 신호가 다르니 둘 다 본다
    for pno, kind in ((1, "벡터 조판"), (2, "스캔본")):
        page = doc[pno]
        lines = page_lines(page)
        regions = figures.plan(page, lines, body, pno)
        assert regions, f"{kind}: 전면 다이어그램에서 잘라낼 영역을 찾지 못했다"

        right = next(l for l in lines if WIDE_LABEL_RIGHT in l["text"])
        assert figures.covers(regions, right), (
            f"{kind}: 그림 오른쪽 절반이 영역 밖이다 — 라벨 "
            f"x{right['x0']:.0f}~{right['x1']:.0f}, "
            f"영역 {[(round(r['rect'][0]), round(r['rect'][2])) for r in regions]}")
        # 본문이나 캡션까지 삼키면 반대 방향 손상이다
        for l in lines:
            if l["size"] >= 7.5 or WIDE_CAPTION in l["text"]:
                assert not figures.covers(regions, l), \
                    f"{kind}: 그림이 아닌 줄이 영역에 삼켜졌다: {l['text']!r}"
    doc.close()


@test
def scan_debris_is_not_a_heading():
    """스캔 잔재는 제목이 될 수 없고, 진짜 제목은 통과해야 한다.

    잔재가 제목으로 승격되면 문단 한가운데에 끼어 문장을 가른다
    (Teece 실측: `…as routines and` / `## il` / 이어지는 본문).
    """
    from post import is_page_number, looks_like_text
    for t in ["ENTERPRISE PERFORMANCE", "DAVID J. TEECE*", "3. METHODS",
              "Nature", "그림 개요", "표 1 요약"]:
        assert looks_like_text(t), f"진짜 제목을 잔재로 버렸다: {t!r}"
    for t in ["il", "* lnf?rSc??Tic??", "?S.SZ o .2", "Isl11?", "C0 g", "MA.", "1350", ""]:
        assert not looks_like_text(t), f"스캔 잔재가 제목이 됐다: {t!r}"

    # 위·아래 여백에 홀로 놓인 숫자는 쪽 번호다 — 쪽마다 값이 달라 반복 판정으로는 못 잡는다
    h = 800.0
    assert is_page_number({"text": "1342", "y0": 40.0}, h)
    assert is_page_number({"text": "1342", "y0": 780.0}, h)
    assert not is_page_number({"text": "1342", "y0": 400.0}, h), "본문 한가운데 숫자는 쪽 번호가 아니다"
    assert not is_page_number({"text": "1342 D. J. Teece", "y0": 40.0}, h)


@test
def sanitize_removes_spaces():
    from post import sanitize
    assert sanitize("Peteraf - 2026 - The Cornerstones") == "Peteraf_-_2026_-_The_Cornerstones"


@test
def postprocess_produces_clean_markdown():
    from post import postprocess
    doc = pymupdf.open(build_fixture())
    # KorDocAI 출력 형태를 모사한다 — 한 줄이 한 문단, 머리글·바닥글은 이미 제거됨
    kordoc_md = "\n\n".join(
        ["## INTRODUCTION"] + P1_PARA1 + P1_PARA2 + P1_RIGHT
        + P2_LEFT + P2_RIGHT + P2_NOTE + P3_LEFT + P3_RIGHT
        + ["![image](image_001.png)"])
    md, stats = postprocess(kordoc_md, doc, ROOT / "work" / "_fixture" / "images", "fixture")
    assert "communication among their units." in md, md
    assert "A second paragraph starts here and ends on this line." in md, md
    assert "image_001.png" not in md, "KorDocAI 이미지 링크는 버려야 한다"
    assert "> **각주 1** See Nelson" in md, md
    assert stats["figures"] == 2 and stats["footnotes"] == 1, stats   # 삽입 그림 1 + 잘라낸 영역 1
    doc.close()


@test
def quality_gate_scores_correctly():
    from quality import score, norm_len
    raw = "가나다라마바사아자차카타파하" * 100 + "."   # 마침표가 없으면 잘린 문단으로 잡힌다
    assert score(raw, raw, 0).ok
    bad = "가나다라마바사아자차카타파하" * 70 + "."     # 30% 유실
    s = score(bad, raw, 0)
    assert not s.ok and s.coverage < 0.97, s
    assert score(bad, raw, dropped_chars=420).ok, "버린 배너는 분모에서 빼야 한다"
    trunc = ("이 문단은 마침표 없이 끝난다 " * 6).strip()
    s2 = score("\n\n".join([trunc] * 4), trunc * 4, 0)
    assert not s2.ok and s2.truncated > 0.03, s2
    assert norm_len("가 나\n다-") == 3


@test
def extract_runs_and_writes_utf8():
    import json, os, shutil, subprocess
    out = ROOT / "work" / "_fixture_run"
    if out.exists():
        shutil.rmtree(out)
    # app.py와 같게 자식 프로세스 출력을 utf-8로 고정한다(윈도우 기본은 cp949)
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run([sys.executable, "scripts/extract.py", str(build_fixture()), "--out", str(out)],
                       cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env)
    assert r.returncode == 0, (r.stdout or "") + (r.stderr or "")
    md = (out / "source.md").read_text(encoding="utf-8")
    assert "communication among their units." in md, md[:400]
    assert "This content downloaded" not in md
    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))  # cp949면 여기서 깨진다
    assert meta["figures"] == 2 and meta["footnotes"] == 1, meta
    assert meta["extractor"] in ("kordoc", "columns", "pymupdf4llm"), meta


@test
def verify_checks_are_strict():
    from verify import check_images, check_numbers, check_citations, check_paragraphs
    wd = ROOT / "work" / "_fixture_run"
    src = "![](images/nope.png)\n\nIn 1993 the value was 3.14 (Peteraf, 1993).\n\n둘째 문단."
    tr = "![](images/nope.png)\n\n1993년 값은 3.14였다 (Peteraf, 1993).\n\n둘째 문단."
    assert check_images(src, tr, wd), "없는 파일은 잡혀야 한다"
    assert check_numbers(src, tr)[0] == []
    assert check_citations(src, tr) == []
    assert check_paragraphs(src, tr) == []
    bad = "값은 였다 (Peteraf, 1991).\n\n둘째 문단."
    assert check_numbers(src, bad)[0], "빠진 연도·소수는 FAIL이어야 한다"
    assert check_citations(src, bad), "인용 변형은 잡혀야 한다"
    assert check_paragraphs(src, bad), "문단 수 불일치는 잡혀야 한다"
    counted = "네 가지 조건이 있다."
    assert check_numbers("There are 4 conditions.", counted)[0] == [], "정수는 WARN까지만"
    assert check_numbers("There are 4 conditions.", counted)[1], "정수 누락은 WARN으로 보고"


@test
def column_path_restores_reading_order():
    import columns
    doc = pymupdf.open(build_fixture())
    md = columns.raw_markdown(doc)
    assert "A. Author" not in md and "This content downloaded" not in md, "반복 요소는 제거된다"
    li, ri = md.index("The model is developed"), md.index("This right column follows")
    assert li < ri, "좌단 전체가 우단보다 먼저 와야 한다"
    assert md.index("Heterogeneity is the first") < md.index("Rents are bound to the firm")
    doc.close()


@test
def figure_region_becomes_image():
    import shutil
    import figures, post
    doc = pymupdf.open(build_fixture())
    out = ROOT / "work" / "_fixture" / "images"
    if out.exists():
        shutil.rmtree(out)
    lines, body, regions = post.ordered_lines(doc)
    assert 2 in regions and regions[2], "3쪽에서 그림 영역을 찾아야 한다"
    texts = [l["text"] for _p, l, _e, _r, _h in lines]
    assert not any("Panel A" in t for t in texts), "도형 안 잔재는 본문에서 빠져야 한다"
    assert any("Figure 1. A sample diagram" in t for t in texts), "캡션은 텍스트로 남아야 한다"
    assert figures.render(doc, regions, out) >= 1
    assert (out / regions[2][0]["name"]).exists()
    doc.close()


@test
def continuations_are_merged():
    from post import merge_continuations
    texts = ["기업은 자원을 결합하여 which involve collective learning and are",
             "> **각주 1** See Nelson (1991).",
             "enhanced as they are applied. 이것이 핵심이다.",
             "## 다음 절 제목",
             "and this must not be merged across a heading."]
    out = merge_continuations(texts)
    assert out[0].startswith("기업은 자원을") and "enhanced as they are applied." in out[0], out
    assert out[1].startswith("> **각주 1**"), "끼어든 각주는 뒤로 옮겨 보존한다"
    assert out[2] == "## 다음 절 제목" and out[3].startswith("and this"), "제목을 넘어 잇지 않는다"


@test
def final_check_catches_untranslated_footnotes():
    import json, shutil
    from final_check import collect
    work, out = ROOT / "work" / "_fc", ROOT / "output" / "_fc"
    for d in (work, out):
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
    src = "본문 문단이다. 원문 자리다. 1993년의 논의를 다룬다.\n\n두 번째 문단이다."
    (work / "source.md").write_text(src, encoding="utf-8")
    (work / "meta.json").write_text(json.dumps(
        {"coverage": 0.99, "truncated": 0.01, "extractor": "columns", "figures": 0}),
        encoding="utf-8")

    good = ("본문 문단이다. 원문 자리다. 1993년의 논의를 다룬다.\n\n두 번째 문단이다."
            "\n\n> **각주 1** 기업이 서로 다른 이유는 Nelson(1991)을 보라.")
    (out / "_fc.ko.md").write_text(good, encoding="utf-8")
    (out / "_fc.html").write_text("<html><body>ok</body></html>", encoding="utf-8")
    rows = collect(work, out)
    assert all(r[3] for r in rows if r[0] == "미번역 각주"), rows

    bad = good.replace("기업이 서로 다른 이유는 Nelson(1991)을 보라.",
                       "See Nelson (1991) and Williams (1992) for discussions on why firms differ.")
    (out / "_fc.ko.md").write_text(bad, encoding="utf-8")
    rows = collect(work, out)
    note_row = next(r for r in rows if r[0] == "미번역 각주")
    assert not note_row[3], "영어로 남은 각주를 잡아야 한다"


@test
def running_head_glued_to_body_is_stripped():
    """kordoc 본문에 남은 러닝헤드를 지운다 — 단독이면 문단째, 붙어 있으면 앞부분만.

    When Does(2026) 실측: 워터마크 `Preprint not peer reviewed`가 40번 나오고 38번이
    제목(`#`)으로 잡혔다. ordered_lines()는 정답지에서만 러닝헤드를 빼므로 kordoc
    마크다운에는 그대로 남아 페이지 경계마다 문단을 갈랐다(잘린 문단 0.198).
    repeated_chars()가 글자 수를 이미 분모에서 빼기 때문에 보존율도 1.057로 튀었다.
    """
    from post import strip_running_heads, repeat_norm
    repeated = {repeat_norm("Preprint not peer reviewed")}
    paras = [(0, "# Preprint not peer reviewed"),
             (1, "# Preprint not peer reviewed define causal states as minimal representations."),
             (2, "이 문단은 손대지 않는다."),
             (3, "## 진짜 제목은 남는다")]
    out = [t for _, t in strip_running_heads(paras, repeated)]
    assert out == ["define causal states as minimal representations.",
                   "이 문단은 손대지 않는다.",
                   "## 진짜 제목은 남는다"], out


HEAD_SIZE_FIXTURE = ROOT / "work" / "_fixture" / "heading_size.pdf"


def build_heading_size_fixture() -> Path:
    """본문 크기가 두 값으로 갈린 한 쪽 PDF.

    When Does(2026) 실측 재현: 본문 10.91이 821줄, 11.96이 275줄이다. 11.96은
    중앙값의 1.096배로 HEADING_MIN(1.08)을 넘지만 BODY_HI(1.12) 안에 있다.
    이 겹치는 구간 때문에, 문장이 끝난 직후에 오는 짧은 본문 조각이 제목으로
    오인됐다(`## tion.`, `## more productive.` 등 11건).
    """
    HEAD_SIZE_FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    page = doc.new_page(width=530, height=800)
    body = [f"Body line {i} runs the full width of this column and ends here."
            for i in range(18)]
    _draw(page, 48, 60, body, 10.9)
    _draw(page, 48, 60 + 18 * 14, ["tion of the argument."], 11.96)
    _draw(page, 48, 60 + 20 * 14, ["A Real Section Heading"], 17.0)
    doc.save(HEAD_SIZE_FIXTURE)
    doc.close()
    return HEAD_SIZE_FIXTURE


@test
def body_size_line_is_not_a_heading():
    """본문 크기 범위 안의 줄은 제목이 아니다.

    문장이 끝난 직후에 오는 짧은 줄은 맥락 조건을 통과하므로, 크기 조건만으로는
    이어지는 본문 조각을 막을 수 없다. figures.body_band가 본문으로 인정하는
    범위 밖일 때만 제목으로 본다.
    """
    from post import build_oracle, key
    doc = pymupdf.open(build_heading_size_fixture())
    o = build_oracle(doc)
    assert key("A Real Section Heading") in o.headings, "진짜 제목은 제목으로 남아야 한다"
    assert key("tion of the argument.") not in o.headings,         "본문 크기(1.096배, 본문 범위 안)인 줄이 제목으로 잡혔다"
    doc.close()


@test
def three_piece_paragraph_is_fully_merged():
    """세 조각으로 갈린 문단은 끝까지 이어야 한다.

    When Does(2026) 실측: 문단이 페이지를 두 번 넘어 세 조각이 됐다. 기존 코드는
    한 번 이은 뒤 결과를 다시 보지 않고 넘어가, 이어붙인 문단이 그대로 문장
    중간에서 끊긴 채 남았다(잘린 문단 27건 중 이어짐 12건이 이것이다).
    """
    from post import merge_continuations
    got = merge_continuations([
        "This sentence begins the paragraph and runs to the end of the page where it is tra-",
        "nslated into a second piece that also fails to close the sentence and ends with",
        "the final piece that closes it properly.",
        "A new paragraph starts here.",
    ])
    assert got == [
        "This sentence begins the paragraph and runs to the end of the page where it is "
        "translated into a second piece that also fails to close the sentence and ends "
        "with the final piece that closes it properly.",
        "A new paragraph starts here.",
    ], got


@test
def math_font_ratio_counts_only_math_spans():
    """줄에서 수학 폰트가 차지하는 문자 비율. 수식 탐지의 필수 신호다.

    When Does·Yin 모두 TeX 조판이라 수식이 CMMI/CMSY/CMR로 조판된다. 본문
    (NimbusRomNo9L-Regu)과 폰트로 갈리므로 좌표보다 확실한 신호다.
    """
    from post import _math_ratio
    assert _math_ratio([{"text": "abcd", "font": "NimbusRomNo9L-Regu"},
                        {"text": "xy", "font": "CMMI10"}]) == 2 / 6
    assert _math_ratio([{"text": "plaintext", "font": "NimbusRomNo9L-Regu"}]) == 0.0
    assert _math_ratio([{"text": "ab", "font": "CMSY10"}]) == 1.0
    assert _math_ratio([]) == 0.0


@test
def display_equation_is_a_region_but_inline_math_is_not():
    """독립 수식 줄만 영역으로 잡는다. 인라인 수식은 건드리지 않는다.

    본문을 이미지로 삼키면 번역이 불가능해지고 보존율 분모가 왜곡된다.
    수학 폰트 비율(필수)과 좁은 줄 폭(보조)을 함께 본다.
    """
    from figures import is_display_equation
    col_x0, col_x1 = 58.0, 528.0
    eq = {"x0": 200.0, "x1": 320.0, "math": 0.8, "text": "A = B + C"}
    assert is_display_equation(eq, col_x0, col_x1), "가운데 조판된 수식 줄"
    full = {"x0": 60.0, "x1": 520.0, "math": 0.12,
            "text": "The model where x = y holds throughout the corpus."}
    assert not is_display_equation(full, col_x0, col_x1), "단 폭을 채운 본문의 인라인 수식"
    prose = {"x0": 60.0, "x1": 200.0, "math": 0.0, "text": "A short prose line."}
    assert not is_display_equation(prose, col_x0, col_x1), "수학 폰트가 없으면 수식이 아니다"


@test
def equation_image_goes_after_the_paragraph_above_it():
    """수식 이미지는 바로 위 문단 뒤에 들어간다.

    캡션이 없어 캡션 앵커를 쓸 수 없고, 페이지 단위 배치는 위치를 잃는다.
    영역에 기록한 '바로 위 본문 줄'을 품은 문단을 찾아 그 뒤에 넣는다.
    """
    from post import insert_equation_links
    regions = {2: [{"kind": "equation", "after_text": "can, therefore, be formulated as",
                    "link": "![](images/eq-p003-01.png)"},
                   # 캡션이 붙은 그림 영역은 이 함수가 건드리지 않는다
                   {"cap_text": "Figure 1. Something", "link": "![](images/fig-p003-02.png)"}]}
    texts = ["The performance score of the n-th attempt can, therefore, be formulated as",
             "Our model formalizes a minimal two-channel search mechanism."]
    got = insert_equation_links(texts, regions)
    assert got == [texts[0], "![](images/eq-p003-01.png)", texts[1]], got


@test
def equation_fragments_are_not_cropped():
    """수학 폰트 조각은 수식 영역이 아니다. 연산자나 수식 번호가 있어야 수식이다.

    When Does 실측: math>=0.3인 줄 115개 중 88개가 공백 뺀 6자 미만 조각(마침표
    하나 등)이었다. 이것까지 잘라내 영역이 51개가 되자 본문에서 글자가 빠지고
    잘린 문단 비율이 0.071에서 0.089로 오히려 나빠졌다.
    """
    from figures import _equation_regions
    lines = [
        {"x0": 60.0, "x1": 520.0, "y0": 100.0, "y1": 112.0, "math": 0.0,
         "text": "The reduced-form extension of the idea-production function is"},
        {"x0": 250.0, "x1": 330.0, "y0": 130.0, "y1": 142.0, "math": 0.9,
         "text": "˙At = θSη"},
        {"x0": 300.0, "x1": 304.0, "y0": 300.0, "y1": 312.0, "math": 1.0, "text": "."},
    ]
    got = _equation_regions(lines, 560.0, 5, [])
    assert len(got) == 1, got
    assert got[0]["kind"] == "equation", got[0]
    assert got[0]["after_text"].startswith("The reduced-form"), got[0]


@test
def whole_math_blocks_leave_the_body_text():
    """통째로 수식인 문단은 본문에서 빠진다. 인라인 수식이 든 본문은 남는다.

    kordoc은 수식을 잘게 조각내 독립 문단으로 내놓는다(When Does 실측: 단위
    1253개 중 75개). 이 조각이 본문 문단 사이에 끼어 문단을 갈랐다. PDF 쪽
    영역(14개)과 개수가 어긋나 1:1로 지울 수 없으므로 텍스트 쪽에서 판정한다.
    """
    from post import drop_math_blocks
    paras = [(0, "The reduced-form extension of the idea-production function is"),
             (1, "A˙ = θ Sη Aφ0+φ1E f t.	(6)"),
             (2, "# ∑"),
             (3, "Every part of this equation has a separate interpretation, where x = y holds."),
             (4, "## 진짜 제목은 남는다")]
    kept, chars = drop_math_blocks(paras)
    assert [t for _, t in kept] == [paras[0][1], paras[3][1], paras[4][1]], kept
    assert chars > 0, chars


@test
def arrow_led_fragment_is_a_continuation():
    """화살표·연산자로 시작하는 줄은 문장을 열 수 없다 — 앞 문단에서 이어진 것이다.

    When Does 실측: `−→ coherent stop–start wave.`, `−→ laboratory and researcher
    incentives`가 소문자 조건에 걸려 병합되지 않아 앞 문단이 잘린 채 남았다.
    """
    from post import merge_continuations
    got = merge_continuations([
        "The example traces local braking then propagation across neighbouring vehicles",
        "−→ coherent stop–start wave.",
        "A new paragraph starts here and is left alone.",
    ])
    assert len(got) == 2, got
    assert got[0].endswith("coherent stop–start wave."), got[0]

    # 여는 인용부호 뒤가 소문자면 문장 도중이다
    quoted = merge_continuations([
        "This prevents a researcher from obtaining a favourable",
        "“emergence score” by combining several weak signals.",
    ])
    assert len(quoted) == 1, quoted
    # 인용으로 문단을 열 때는 안쪽이 대문자다 — 붙이지 않는다
    opening = merge_continuations([
        "The author closes the argument without a full stop here",
        "“Evidence for change is what matters,” he wrote later.",
    ])
    assert len(opening) == 2, opening


@test
def math_dominant_table_region_is_an_equation():
    """표로 잡힌 영역이 수식 조판이면 수식으로 되돌린다.

    Yin(2026)의 큰 시그마는 2차원으로 조판돼 `xn =`, `B`, `X`, `b=1` 같은 조각으로
    흩어진다. pymupdf의 find_tables가 이 격자를 표로 먼저 claim해 수식 탐지가
    닿지 못했고(문서 전체에서 수식 영역이 2개만 잡혔다), 그래서 문단이
    `…be formulated as`에서 끊긴 채 이미지도 놓이지 않았다.
    """
    from figures import _math_dominant
    rect = (200.0, 600.0, 330.0, 660.0)
    equation = [{"x0": 210.0, "x1": 240.0, "y0": 620.0, "y1": 632.0, "math": 1.0,
                 "text": "xn ="},
                {"x0": 250.0, "x1": 266.0, "y0": 629.0, "y1": 641.0, "math": 1.0,
                 "text": "wbx(b)"},
                {"x0": 250.0, "x1": 264.0, "y0": 647.0, "y1": 659.0, "math": 0.4,
                 "text": "b=1"}]
    assert _math_dominant(equation, rect), "수식 조판이면 수식 영역이다"

    real_table = [{"x0": 210.0, "x1": 300.0, "y0": 620.0, "y1": 632.0, "math": 0.0,
                   "text": "Region North South Total"},
                  {"x0": 210.0, "x1": 300.0, "y0": 640.0, "y1": 652.0, "math": 0.0,
                   "text": "Sales 120 340 460"}]
    assert not _math_dominant(real_table, rect), "진짜 표는 표로 남는다"
    assert not _math_dominant([], rect), "빈 영역은 수식이 아니다"


@test
def equation_anchor_is_the_line_above_in_the_same_column():
    """수식이 오른쪽으로 밀려 조판돼도 도입 문장을 앵커로 잡는다.

    Yin(2026) 실측: 수식 영역은 x 280~354인데 도입 문장은 x 72~267에서 끝난다.
    가로 겹침을 요구하면 이 문장이 후보에서 탈락하고 엉뚱한 윗줄이 앵커가 되어,
    수식 이미지가 다른 문단 뒤로 갔다. 문단은 `…be formulated as`에서 끊긴 채
    남아 게이트를 막았다(0.062). 겹침이 아니라 같은 단인지를 본다.
    """
    from figures import _anchor_above
    lines = [
        {"x0": 72.0, "x1": 538.0, "y0": 575.0, "y1": 589.0, "math": 0.0,
         "text": "The overall performance score of the solution is a weighted sum."},
        {"x0": 72.0, "x1": 267.0, "y0": 596.0, "y1": 608.0, "math": 0.0,
         "text": "n-th attempt can, therefore, be formulated as"},
        {"x0": 294.0, "x1": 340.0, "y0": 629.0, "y1": 641.0, "math": 1.0,
         "text": "wbx(b)"},
    ]
    got = _anchor_above(lines, (280.0, 625.0, 354.0, 659.0), 595.0)
    assert got.endswith("be formulated as"), repr(got)


@test
def pdf_export_works_or_degrades():
    import shutil
    import to_pdf
    out = ROOT / "work" / "_fixture"
    out.mkdir(parents=True, exist_ok=True)
    html, pdf = out / "pdf_test.html", out / "pdf_test.pdf"
    html.write_text("<html><head><meta charset='utf-8'><title>t</title></head>"
                    "<body><h1>한글 제목</h1><p>본문 문단이다.</p></body></html>",
                    encoding="utf-8")
    pdf.unlink(missing_ok=True)
    if not to_pdf.find_browser():
        print("     (Edge·Chrome 없음 — 실패해도 예외를 던지지 않는지만 확인)")
        assert to_pdf.html_to_pdf(html, pdf) is False
        return
    assert to_pdf.html_to_pdf(html, pdf), "브라우저가 있으면 PDF가 나와야 한다"
    assert pdf.exists() and pdf.stat().st_size > 0
    doc = pymupdf.open(pdf)
    assert "한글 제목" in doc[0].get_text(), doc[0].get_text()[:100]
    doc.close()
    # 없는 폴더는 만들어서 쓴다
    nested = out / "_pdf_nested" / "x.pdf"
    shutil.rmtree(nested.parent, ignore_errors=True)
    assert to_pdf.html_to_pdf(html, nested) and nested.exists()
    shutil.rmtree(nested.parent, ignore_errors=True)
    # 없는 HTML은 예외 없이 False
    assert to_pdf.html_to_pdf(out / "없는파일.html", pdf) is False


def main():
    names = sys.argv[1:] or list(TESTS)
    unknown = [n for n in names if n not in TESTS]
    if unknown:
        sys.exit(f"없는 테스트: {unknown}\n가능: {list(TESTS)}")
    failed = []
    for n in names:
        try:
            TESTS[n]()
            print(f"ok   {n}")
        except Exception:
            failed.append(n)
            print(f"FAIL {n}")
            traceback.print_exc()
    print(f"\n{len(names) - len(failed)}/{len(names)} 통과")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
