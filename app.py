#!/usr/bin/env python3
"""논문 번역기 웹 UI — 브라우저에서 PDF/DOCX를 업로드하면 자동으로 번역 파이프라인을 실행한다.

업로드 → input/ 저장 → `claude -p "/translate input/<file>"` 백그라운드 실행
→ work/<stem>/ 진행 상황을 3초마다 폴링 → 완료되면 output/<stem>/<stem>.html 열람.

실행:  python app.py   (또는 논문번역기.bat 더블클릭)  →  http://localhost:8765
"""
import json, os, re, shutil, subprocess, sys
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_file

ROOT = Path(__file__).parent.resolve()
INPUT, WORK, OUTPUT = ROOT / "input", ROOT / "work", ROOT / "output"
ALLOWED = {".pdf", ".docx"}
PORT = 8765

CLAUDE = shutil.which("claude.cmd") or shutil.which("claude")
app = Flask(__name__)
procs: dict[str, subprocess.Popen] = {}  # stem -> running claude process


# ---------------------------------------------------------------- pipeline
def start_translation(fname: str) -> None:
    stem = Path(fname).stem
    WORK.mkdir(exist_ok=True)
    log = open(WORK / f"{stem}.claude.log", "w", encoding="utf-8")
    cmd = [
        CLAUDE, "-p", f"/translate input/{fname}",
        "--output-format", "text",
        "--no-session-persistence",
        "--allowedTools", "Bash(python:*)", "Read", "Write", "Edit", "Glob", "Grep", "Task",
    ]
    # CLAUDE* 변수를 제거해야 Claude Code 세션 안에서 서버를 띄웠을 때도
    # 자식 claude 프로세스가 "중첩 세션" 차단에 걸리지 않는다.
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
    env["PYTHONIOENCODING"] = "utf-8"
    procs[stem] = subprocess.Popen(
        cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, env=env,
    )


def job_status(stem: str, src_name: str | None) -> dict:
    wd = WORK / stem
    html = OUTPUT / stem / f"{stem}.html"
    p = procs.get(stem)
    running = p is not None and p.poll() is None

    status, phase, pct = "uploaded", "대기 중", 0
    if html.exists() and not running:
        status, phase, pct = "done", "완료", 100
    elif running:
        status = "running"
        idx = wd / "chunks" / "index.json"
        if not (wd / "source.md").exists():
            phase, pct = "1/5 원문 추출 중", 4
        elif not idx.exists():
            phase, pct = "1/5 청크 분할 중", 6
        else:
            try:
                n = max(len(json.loads(idx.read_text(encoding="utf-8"))), 1)
            except Exception:
                n = 1
            t = len(list((wd / "translated").glob("*.md"))) if (wd / "translated").exists() else 0
            r = len(list((wd / "review").glob("*.md"))) if (wd / "review").exists() else 0
            if r:
                phase, pct = f"4/5 검수 중 ({r}/{n})", 70 + round(25 * r / n)
            elif t >= n:
                phase, pct = "4/5 검수 준비", 70
            elif t or (wd / "glossary.md").exists():
                phase, pct = f"3/5 번역 중 ({t}/{n})", 25 + round(45 * t / n)
            else:
                phase, pct = "2/5 용어표 작성 중", 12
    elif p is not None:  # process finished but no output → failure
        status, phase = "failed", "실패 — 로그 확인"

    return {"stem": stem, "file": src_name or "", "status": status, "phase": phase, "pct": pct}


def list_jobs() -> list[dict]:
    src = {}  # stem -> input filename
    if INPUT.exists():
        for f in sorted(INPUT.iterdir()):
            if f.suffix.lower() in ALLOWED:
                src.setdefault(f.stem, f.name)
    stems = dict.fromkeys(list(src) + [d.name for d in OUTPUT.iterdir() if d.is_dir()] if OUTPUT.exists() else list(src))
    order = sorted(stems, key=lambda s: -(INPUT / src[s]).stat().st_mtime if s in src else 0)
    return [job_status(s, src.get(s)) for s in order]


def safe_stem(stem: str) -> str:
    if not re.fullmatch(r"[^\\/:*?\"<>|]+", stem) or stem in (".", ".."):
        abort(400)
    return stem


# ---------------------------------------------------------------- routes
@app.get("/")
def index():
    return PAGE


@app.get("/status")
def status():
    return jsonify(list_jobs())


@app.post("/upload")
def upload():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "파일이 없습니다"}), 400
    name = Path(f.filename).name
    if Path(name).suffix.lower() not in ALLOWED:
        return jsonify({"error": "PDF 또는 DOCX만 지원합니다"}), 400
    stem = Path(name).stem
    if stem in procs and procs[stem].poll() is None:
        return jsonify({"error": f"'{stem}'은(는) 이미 번역 중입니다"}), 409
    INPUT.mkdir(exist_ok=True)
    f.save(INPUT / name)
    start_translation(name)
    return jsonify({"ok": True, "stem": stem})


@app.post("/retry/<stem>")
def retry(stem):
    stem = safe_stem(stem)
    if stem in procs and procs[stem].poll() is None:
        return jsonify({"error": "이미 번역 중입니다"}), 409
    match = [f for f in INPUT.iterdir() if f.stem == stem and f.suffix.lower() in ALLOWED]
    if not match:
        return jsonify({"error": "input/에 원본 파일이 없습니다"}), 404
    start_translation(match[0].name)
    return jsonify({"ok": True})


@app.get("/view/<stem>")
def view(stem):
    p = OUTPUT / safe_stem(stem) / f"{stem}.html"
    if not p.exists():
        abort(404)
    return send_file(p)


@app.get("/md/<stem>")
def md(stem):
    p = OUTPUT / safe_stem(stem) / f"{stem}.ko.md"
    if not p.exists():
        abort(404)
    return send_file(p, as_attachment=True)


@app.get("/log/<stem>")
def log(stem):
    p = WORK / f"{safe_stem(stem)}.claude.log"
    text = p.read_text(encoding="utf-8", errors="replace")[-8000:] if p.exists() else "(로그 없음)"
    return app.response_class(text, mimetype="text/plain; charset=utf-8")


# ---------------------------------------------------------------- page
PAGE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>논문 번역기</title>
<style>
  * { box-sizing:border-box; margin:0; padding:0; }
  body { font-family:'Malgun Gothic','맑은 고딕',sans-serif; background:#f4f6f8; color:#222; }
  .wrap { max-width:760px; margin:36px auto; padding:0 16px; }
  h1 { font-size:1.5em; color:#1a5276; border-bottom:2.2px solid #1a5276; padding-bottom:.35em; }
  .sub { color:#556; font-size:.85em; margin:.5em 0 1.4em; }
  #drop { background:#fff; border:2.5px dashed #9db6c8; border-radius:10px; padding:44px 20px;
          text-align:center; color:#456; cursor:pointer; transition:.15s; }
  #drop.on, #drop:hover { border-color:#1a5276; background:#eef3f7; }
  #drop b { color:#1a5276; }
  #drop .small { font-size:.8em; color:#789; margin-top:.5em; }
  #msg { min-height:1.4em; margin:.6em 2px; font-size:.85em; color:#b03a2e; }
  .job { background:#fff; border:1px solid #dde4ea; border-radius:8px; padding:14px 18px;
         margin:10px 0; box-shadow:0 1px 4px rgba(26,47,66,.06); }
  .job .top { display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
  .job .name { font-weight:bold; flex:1; min-width:180px; word-break:break-all; }
  .pill { font-size:.74em; padding:.2em .7em; border-radius:99px; white-space:nowrap; }
  .pill.done    { background:#e3f4e8; color:#1e7e34; }
  .pill.running { background:#eef3f7; color:#1a5276; }
  .pill.failed  { background:#fdeceb; color:#b03a2e; }
  .pill.uploaded{ background:#f0f2f4; color:#667; }
  .bar { height:6px; background:#e8edf1; border-radius:99px; margin-top:10px; overflow:hidden; }
  .bar i { display:block; height:100%; background:#1a5276; border-radius:99px; transition:width .8s; }
  .btns { display:flex; gap:8px; margin-top:10px; flex-wrap:wrap; }
  .btns a, .btns button { font:inherit; font-size:.82em; text-decoration:none; cursor:pointer;
        padding:.35em 1em; border-radius:6px; border:1px solid #1a5276; color:#1a5276; background:#fff; }
  .btns a.primary { background:#1a5276; color:#fff; }
  .btns a:hover, .btns button:hover { background:#eef3f7; }
  .btns a.primary:hover { background:#154466; }
  .empty { text-align:center; color:#99a; padding:28px 0; font-size:.9em; }
</style>
</head>
<body>
<div class="wrap">
  <h1>논문 번역기</h1>
  <div class="sub">영어 논문(PDF·DOCX)을 올리면 용어표 작성 → 완역 → 검수 → HTML 생성까지 자동으로 진행됩니다.</div>
  <div id="drop">
    <div><b>논문 파일을 여기에 끌어다 놓거나 클릭해서 선택</b></div>
    <div class="small">PDF · DOCX / 업로드하면 바로 번역이 시작됩니다 (논문 분량에 따라 수 분~수십 분)</div>
    <input type="file" id="file" accept=".pdf,.docx" hidden>
  </div>
  <div id="msg"></div>
  <div id="jobs"><div class="empty">아직 번역한 논문이 없습니다.</div></div>
</div>
<script>
const drop = document.getElementById('drop'), file = document.getElementById('file'),
      msg = document.getElementById('msg'), jobsEl = document.getElementById('jobs');

drop.onclick = () => file.click();
['dragover','dragenter'].forEach(e => drop.addEventListener(e, ev => { ev.preventDefault(); drop.classList.add('on'); }));
['dragleave','drop'].forEach(e => drop.addEventListener(e, ev => { ev.preventDefault(); drop.classList.remove('on'); }));
drop.addEventListener('drop', ev => { if (ev.dataTransfer.files.length) send(ev.dataTransfer.files[0]); });
file.onchange = () => { if (file.files.length) send(file.files[0]); file.value = ''; };

async function send(f) {
  msg.style.color = '#1a5276'; msg.textContent = '업로드 중… ' + f.name;
  const fd = new FormData(); fd.append('file', f);
  try {
    const r = await fetch('/upload', { method:'POST', body: fd });
    const j = await r.json();
    if (!r.ok) { msg.style.color = '#b03a2e'; msg.textContent = j.error || '업로드 실패'; return; }
    msg.textContent = '번역을 시작했습니다: ' + f.name;
    poll();
  } catch (e) { msg.style.color = '#b03a2e'; msg.textContent = '서버에 연결할 수 없습니다'; }
}

async function retry(stem) {
  await fetch('/retry/' + encodeURIComponent(stem), { method:'POST' }); poll();
}

function render(jobs) {
  if (!jobs.length) { jobsEl.innerHTML = '<div class="empty">아직 번역한 논문이 없습니다.</div>'; return; }
  const label = { done:'완료', running:'번역 중', failed:'실패', uploaded:'대기' };
  const pillText = j => (j.status === 'running' || j.status === 'failed') ? j.phase : label[j.status];
  jobsEl.innerHTML = jobs.map(j => {
    const s = encodeURIComponent(j.stem);
    let btns = '';
    if (j.status === 'done')
      btns = `<a class="primary" href="/view/${s}" target="_blank">번역본 보기</a>
              <a href="/md/${s}">MD 내려받기</a>
              <button onclick="retry('${j.stem.replace(/'/g,"\\\\'")}')">다시 번역</button>`;
    else if (j.status === 'failed')
      btns = `<a href="/log/${s}" target="_blank">로그 보기</a>
              <button onclick="retry('${j.stem.replace(/'/g,"\\\\'")}')">다시 시도</button>`;
    else if (j.status === 'running')
      btns = `<a href="/log/${s}" target="_blank">로그 보기</a>`;
    return `<div class="job">
      <div class="top">
        <span class="name">${j.stem}</span>
        <span class="pill ${j.status}">${pillText(j)}</span>
      </div>
      ${j.status === 'running' ? `<div class="bar"><i style="width:${j.pct}%"></i></div>` : ''}
      ${btns ? `<div class="btns">${btns}</div>` : ''}
    </div>`;
  }).join('');
}

async function poll() {
  try { render(await (await fetch('/status')).json()); } catch (e) {}
}
poll(); setInterval(poll, 3000);
</script>
</body>
</html>"""


if __name__ == "__main__":
    if not CLAUDE:
        sys.exit("claude CLI를 찾을 수 없습니다. Claude Code가 설치되어 있어야 합니다.")
    print(f"논문 번역기 → http://localhost:{PORT}")
    app.run(host="127.0.0.1", port=PORT, debug=False)
