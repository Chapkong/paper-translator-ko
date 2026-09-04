#!/usr/bin/env python3
"""Step 7 — Render output/<stem>/<stem>.ko.md as a self-contained HTML page.

Images are embedded as base64 data URIs, so the single .html file can be
opened, shared, or uploaded anywhere without the images/ folder.
Style follows the paper-analyzer template (A4 sheet, Malgun Gothic, #1a5276).

Usage: python scripts/to_html.py output/<stem>
Writes output/<stem>/<stem>.html
"""
import base64, mimetypes, re, sys
from pathlib import Path

import markdown

TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ font-family:'Malgun Gothic','맑은 고딕',sans-serif; background:#f4f6f8; color:#222; }}
  #a4 {{ max-width:210mm; margin:20px auto; background:#fff; box-shadow:0 2px 14px rgba(0,0,0,.15);
        padding:14mm 13mm 16mm; font-size:11pt; line-height:1.6; }}
  #a4 h1 {{ font-size:1.35em; color:#1a5276; text-align:center; border-bottom:2.2px solid #1a5276;
           padding-bottom:.4em; margin-bottom:.3em; }}
  #a4 h1 + p {{ text-align:center; font-size:.85em; color:#555; margin-bottom:1em; }}
  #a4 h2 {{ font-size:1.05em; color:#1a5276; background:#eef3f7; padding:.22em .55em;
           margin:1em 0 .45em; border-left:3.5px solid #1a5276; }}
  #a4 h3 {{ font-size:1em; color:#1a5276; margin:.8em 0 .3em; }}
  #a4 p {{ margin:.45em 0; text-align:justify; }}
  #a4 img {{ display:block; max-width:88%; margin:.6em auto .2em; border:1px solid #ddd; border-radius:4px; }}
  #a4 img + p, #a4 p:has(img) + p {{ text-align:center; font-size:.85em; color:#555; }}
  #a4 table {{ border-collapse:collapse; margin:.7em auto; font-size:.92em; }}
  #a4 th, #a4 td {{ border:1px solid #b9c6d0; padding:.28em .7em; text-align:center; }}
  #a4 th {{ background:#eef3f7; color:#1a5276; }}
  #a4 hr {{ border:none; border-top:1.5px dashed #b9c6d0; margin:1.2em 0; }}
  #a4 code {{ font-family:Consolas,monospace; background:#f0f2f4; padding:0 .25em; border-radius:3px; }}
  @page {{ size:A4; margin:12mm; }}
  @media print {{ body {{ background:#fff; }} #a4 {{ box-shadow:none; margin:0; max-width:none; }} }}
</style>
</head>
<body>
<div id="a4">
{body}
</div>
</body>
</html>
"""


def embed_images(html: str, base: Path) -> str:
    def repl(m):
        src = m.group(1)
        p = base / src
        if not p.exists():
            return m.group(0)
        mime = mimetypes.guess_type(p.name)[0] or "image/png"
        b64 = base64.b64encode(p.read_bytes()).decode()
        return m.group(0).replace(src, f"data:{mime};base64,{b64}")
    return re.sub(r'<img[^>]+src="([^"]+)"', repl, html)


def main():
    outdir = Path(sys.argv[1])
    md_path = outdir / f"{outdir.name}.ko.md"
    if not md_path.exists():
        sys.exit(f"not found: {md_path}")
    md_text = md_path.read_text(encoding="utf-8")

    body = markdown.markdown(md_text, extensions=["tables"])
    body = embed_images(body, outdir)

    m = re.search(r"^#\s+(.+)$", md_text, re.M)
    title = m.group(1).strip() if m else outdir.name

    html_path = outdir / f"{outdir.name}.html"
    html_path.write_text(TEMPLATE.format(title=title, body=body), encoding="utf-8")
    print(f"→ {html_path}  ({html_path.stat().st_size:,} bytes, self-contained)")


if __name__ == "__main__":
    main()
