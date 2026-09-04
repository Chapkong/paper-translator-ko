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
    assert o.page_last[2] == key("Implications for research are"), o.page_last[2]
    paras = insert_images(["The final section applies the model to strategy formulation.",
                           "Implications for research are discussed at the end."], by_page, o)
    assert paras[-1].startswith("![](images/"), paras
    assert strip_kordoc_images("본문\n\n![image](image_001.png)\n\n다음") == "본문\n\n다음"
    doc.close()


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
    assert stats["figures"] == 1 and stats["footnotes"] == 1, stats
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
    assert meta["figures"] == 1 and meta["coverage"] >= 0.97, meta
    assert meta["extractor"] in ("kordoc", "pymupdf4llm"), meta


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
