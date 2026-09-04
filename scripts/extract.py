#!/usr/bin/env python3
"""Step 1 — Extract a paper (PDF or DOCX) to Markdown, keeping figures as image files.

Usage:  python scripts/extract.py input/paper.pdf  [--out work/<stem>]

Output layout (work/<stem>/):
    source.md        Markdown with ![](images/xxx.png) links where figures were
    images/          extracted figure/image files (left untouched by translation)
    meta.json        page count, figure count, source type
"""
import argparse, json, os, re, shutil, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import quality


def extract_pdf(src: Path, outdir: Path):
    """KorDocAI CLI + 후처리. 반환: (markdown, stats, raw_text) — 실패 시 md는 None."""
    import pymupdf
    import kordoc, post

    raw_md = kordoc.to_markdown(src)
    doc = pymupdf.open(str(src))
    raw_text = "".join(doc[i].get_text() for i in range(doc.page_count))
    if raw_md is None:
        doc.close()
        return None, {}, raw_text
    md, stats = post.postprocess(raw_md, doc, outdir / "images", src.stem)
    doc.close()
    stats["extractor"] = "kordoc"
    return md, stats, raw_text


def extract_pdf_legacy(src: Path, outdir: Path) -> str:
    import pymupdf4llm
    img_dir = outdir / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    md = pymupdf4llm.to_markdown(
        str(src),
        write_images=True,
        image_path=str(img_dir),
        image_format="png",
        dpi=150,
        page_chunks=False,
    )
    # pymupdf4llm writes absolute/relative paths; normalise to images/<file>
    md = re.sub(r"!\[[^\]]*\]\([^)]*?/?images/([^)]+)\)", r"![](images/\1)", md)
    md = re.sub(r"!\[[^\]]*\]\((?!images/)[^)]*?([^/)]+\.png)\)", r"![](images/\1)", md)
    return md


def extract_docx(src: Path, outdir: Path) -> str:
    import mammoth
    img_dir = outdir / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    counter = {"n": 0}

    def save_image(image):
        counter["n"] += 1
        ext = image.content_type.split("/")[-1].replace("jpeg", "jpg")
        name = f"fig_{counter['n']:03d}.{ext}"
        with image.open() as f, open(img_dir / name, "wb") as out:
            out.write(f.read())
        return {"src": f"images/{name}"}

    # DOCX → HTML (mammoth keeps tables/headings/images) → Markdown (markdownify renders tables)
    from markdownify import markdownify
    with open(src, "rb") as f:
        result = mammoth.convert_to_html(
            f, convert_image=mammoth.images.img_element(save_image)
        )
    md = markdownify(result.value, heading_style="ATX", escape_underscores=False,
                     escape_asterisks=False, escape_misc=False)
    return md


def clean(md: str) -> str:
    md = re.sub(r"\n{3,}", "\n\n", md)          # collapse blank runs
    md = re.sub(r"-----+\n", "", md)              # pymupdf page separators
    # OCR'd text inside figures is noise for translation — the figure itself is kept as an image
    md = re.sub(r"<!-- Start of picture text -->.*?<!-- End of picture text -->\n?", "", md, flags=re.S)
    md = re.sub(r"^(#{1,6})\s+\*\*(.+?)\*\*\s*$", r"\1 \2", md, flags=re.M)  # ## **Title** → ## Title
    md = re.sub(r"[ \t]+$", "", md, flags=re.M)
    md = md.replace("­", "")                 # soft hyphens
    return md.strip() + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    src = Path(a.src).resolve()
    if not src.exists():
        sys.exit(f"not found: {src}")
    outdir = Path(a.out) if a.out else Path("work") / src.stem
    if outdir.exists():
        shutil.rmtree(outdir)
    outdir.mkdir(parents=True)

    ext = src.suffix.lower()
    if ext == ".pdf":
        md, stats, raw_text = extract_pdf(src, outdir)
        s = None
        if md:
            md = clean(md)
            s = quality.score(md, raw_text, stats.get("dropped_chars", 0))
        if s is None or not s.ok:              # 폴백 — 기존 pymupdf4llm 경로
            shutil.rmtree(outdir / "images", ignore_errors=True)   # 1차 경로 이미지 제거
            md2 = clean(extract_pdf_legacy(src, outdir))
            s2 = quality.score(md2, raw_text, 0)
            if s is None or quality.better(s, s2):
                md, s = md2, s2
                stats = {**stats, "extractor": "pymupdf4llm",
                         "figures": len(list((outdir / "images").glob("*")))}
        if not s.ok:
            (outdir / "extract_report.md").write_text(quality.report(s, md), encoding="utf-8")
            (outdir / "source.md").write_text(md, encoding="utf-8")
            sys.exit(f"추출 품질 미달 — 보존율 {s.coverage:.3f}, 잘린 문단 {s.truncated:.3f}. "
                     f"번역을 시작하지 않는다. 리포트: {outdir / 'extract_report.md'}")
    elif ext == ".docx":
        md = clean(extract_docx(src, outdir))
        s = quality.Score(1.0, quality.truncated_ratio(md), True)
        stats = {"extractor": "mammoth", "figures": len(list((outdir / "images").glob("*")))}
    else:
        sys.exit("supported: .pdf .docx")

    (outdir / "source.md").write_text(md, encoding="utf-8")
    meta = {"source": str(src), "type": ext[1:], "chars": len(md),
            "figures": stats.get("figures", 0), "footnotes": stats.get("footnotes", 0),
            "extractor": stats.get("extractor", "unknown"),
            "coverage": round(s.coverage, 4), "truncated": round(s.truncated, 4)}
    (outdir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False),
                                      encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False))
    print(f"→ {outdir/'source.md'}")


if __name__ == "__main__":
    main()
