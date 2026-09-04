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


def extract_pdf(src: Path, outdir: Path) -> str:
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
        md = extract_pdf(src, outdir)
    elif ext == ".docx":
        md = extract_docx(src, outdir)
    else:
        sys.exit("supported: .pdf .docx")

    md = clean(md)
    (outdir / "source.md").write_text(md, encoding="utf-8")
    n_img = len(list((outdir / "images").glob("*")))
    meta = {"source": str(src), "type": ext[1:], "chars": len(md), "figures": n_img}
    (outdir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    print(json.dumps(meta, ensure_ascii=False))
    print(f"→ {outdir/'source.md'}")


if __name__ == "__main__":
    main()
