#!/usr/bin/env python3
"""
Mini review server for tagging He/Hu diary pages.

Usage:
    python3 scripts/review_server.py
    open http://localhost:8765

Tags written to: data/review/senesh_diary_hehe_tags.json
  { "p0001": "he", "p0002": "hu", "p0003": "mixed", "p0042": "skip", ... }

Tag meanings:
  he    — Hebrew only            (in scope, keep)
  mixed — Hebrew + Hungarian     (in scope, keep)
  hu    — Hungarian only         (out of scope, remove)
  skip  — Unsure, flag for later
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parents[1]
SOURCE_ID = "nli__nnl_archive_al997009912248705171"
SCANS_DIR = REPO / "data" / "scans" / SOURCE_ID
TAGS_PATH = REPO / "data" / "review" / "senesh_diary_hehe_tags.json"
PORT = 8765

PAGES = sorted(p.name for p in SCANS_DIR.glob("*.jpg"))


def load_tags():
    if TAGS_PATH.exists():
        return json.loads(TAGS_PATH.read_text())
    return {}


def save_tags(tags):
    TAGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    TAGS_PATH.write_text(json.dumps(tags, indent=2, sort_keys=True) + "\n")


HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>He/Hu Diary Page Review</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: system-ui, sans-serif; background: #1a1a1a; color: #eee;
         display: flex; flex-direction: column; height: 100vh; overflow: hidden; }

  #header { padding: 10px 16px; background: #111; display: flex;
            align-items: center; gap: 16px; flex-shrink: 0; }
  #progress-wrap { flex: 1; background: #333; border-radius: 4px; height: 8px; }
  #progress-bar { height: 8px; background: #4a9; border-radius: 4px; transition: width .2s; }
  #status { font-size: 13px; white-space: nowrap; min-width: 180px; }
  #page-label { font-size: 15px; font-weight: 600; min-width: 90px; }

  #img-wrap { flex: 1; display: flex; align-items: center; justify-content: center;
              overflow: hidden; padding: 8px; }
  #scan { max-width: 100%; max-height: 100%; object-fit: contain;
          border-radius: 4px; box-shadow: 0 4px 24px #0008; }

  #controls { flex-shrink: 0; padding: 12px 16px; background: #111;
              display: flex; align-items: center; justify-content: center; gap: 10px; }
  .btn { padding: 10px 24px; border: none; border-radius: 6px; font-size: 15px;
         font-weight: 600; cursor: pointer; transition: opacity .1s, transform .1s; }
  .btn:active { transform: scale(.96); }
  .btn:disabled { opacity: .35; cursor: default; }
  #btn-he    { background: #2a7; color: #fff; }
  #btn-mixed { background: #57a; color: #fff; }
  #btn-hu    { background: #c44; color: #fff; }
  #btn-skip  { background: #555; color: #ccc; }
  #btn-back  { background: #333; color: #aaa; padding: 10px 14px; }
  .key-hint  { font-size: 11px; opacity: .6; display: block; text-align: center; margin-top: 2px; }

  #tag-badge { position: fixed; top: 52px; right: 16px; padding: 6px 14px;
               border-radius: 20px; font-size: 13px; font-weight: 700;
               opacity: 0; transition: opacity .3s; pointer-events: none; }
  #tag-badge.show { opacity: 1; }
  #tag-badge.he    { background: #2a7; color: #fff; }
  #tag-badge.mixed { background: #57a; color: #fff; }
  #tag-badge.hu    { background: #c44; color: #fff; }
  #tag-badge.skip  { background: #555; color: #ccc; }

  #done-screen { display: none; flex-direction: column; align-items: center;
                 justify-content: center; height: 100vh; gap: 16px; }
  #done-screen h1 { font-size: 2rem; }
  #counts { font-size: 15px; line-height: 2; text-align: center; color: #aaa; }
</style>
</head>
<body>

<div id="header">
  <span id="page-label">p0001</span>
  <div id="progress-wrap"><div id="progress-bar" style="width:0%"></div></div>
  <span id="status">0 / 101 tagged</span>
</div>

<div id="img-wrap">
  <img id="scan" src="" alt="scan">
</div>

<div id="controls">
  <div>
    <button class="btn" id="btn-back">◀</button>
    <span class="key-hint">←</span>
  </div>
  <div>
    <button class="btn" id="btn-he">Hebrew only</button>
    <span class="key-hint">H</span>
  </div>
  <div>
    <button class="btn" id="btn-mixed">Mixed</button>
    <span class="key-hint">M</span>
  </div>
  <div>
    <button class="btn" id="btn-hu">Hungarian only</button>
    <span class="key-hint">U</span>
  </div>
  <div>
    <button class="btn" id="btn-skip">Skip</button>
    <span class="key-hint">S</span>
  </div>
</div>

<div id="tag-badge"></div>

<div id="done-screen">
  <h1>✓ All pages reviewed</h1>
  <div id="counts"></div>
  <p style="color:#666;font-size:13px">Tags saved — tell Claude you're done.</p>
</div>

<script>
const PAGES = __PAGES_JSON__;
let tags = __TAGS_JSON__;
let idx = 0;

// Start at first untagged page
for (let i = 0; i < PAGES.length; i++) {
  const stem = PAGES[i].replace('.jpg','');
  if (!tags[stem]) { idx = i; break; }
  if (i === PAGES.length - 1) idx = PAGES.length; // all done
}

function stem(i) { return PAGES[i].replace('.jpg',''); }

function render() {
  if (idx >= PAGES.length) { showDone(); return; }
  const page = PAGES[idx];
  const s = stem(idx);
  document.getElementById('scan').src = '/scans/' + page;
  document.getElementById('page-label').textContent = s.split('__').pop();
  const tagged = Object.keys(tags).length;
  document.getElementById('status').textContent =
    tagged + ' / ' + PAGES.length + ' tagged';
  document.getElementById('progress-bar').style.width =
    (tagged / PAGES.length * 100).toFixed(1) + '%';
  document.getElementById('btn-back').disabled = idx === 0;

  // Show existing tag if revisiting
  const existing = tags[s];
  if (existing) flashBadge(existing);
}

function tag(value) {
  const s = stem(idx);
  tags[s] = value;
  fetch('/tag', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({page: s, tag: value})
  });
  flashBadge(value);
  idx++;
  render();
}

function flashBadge(value) {
  const b = document.getElementById('tag-badge');
  const labels = {he:'Hebrew only', mixed:'Mixed', hu:'Hungarian only', skip:'Skip'};
  b.textContent = labels[value] || value;
  b.className = 'show ' + value;
  clearTimeout(b._t);
  b._t = setTimeout(() => b.classList.remove('show'), 900);
}

function showDone() {
  document.getElementById('done-screen').style.display = 'flex';
  document.querySelector('body > *:not(#done-screen)') && null;
  document.getElementById('header').style.display = 'none';
  document.getElementById('img-wrap').style.display = 'none';
  document.getElementById('controls').style.display = 'none';
  const counts = {he:0, mixed:0, hu:0, skip:0};
  Object.values(tags).forEach(v => { if (counts[v] !== undefined) counts[v]++; });
  document.getElementById('counts').innerHTML =
    `Hebrew only: <b>${counts.he}</b><br>` +
    `Mixed: <b>${counts.mixed}</b><br>` +
    `Hungarian only: <b>${counts.hu}</b><br>` +
    `Skip / unsure: <b>${counts.skip}</b>`;
}

document.getElementById('btn-he').onclick    = () => tag('he');
document.getElementById('btn-mixed').onclick = () => tag('mixed');
document.getElementById('btn-hu').onclick    = () => tag('hu');
document.getElementById('btn-skip').onclick  = () => tag('skip');
document.getElementById('btn-back').onclick  = () => { if (idx > 0) { idx--; render(); } };

document.addEventListener('keydown', e => {
  if (e.repeat) return;
  if (e.key === 'h' || e.key === 'H') tag('he');
  else if (e.key === 'm' || e.key === 'M') tag('mixed');
  else if (e.key === 'u' || e.key === 'U') tag('hu');
  else if (e.key === 's' || e.key === 'S') tag('skip');
  else if (e.key === 'ArrowLeft') { if (idx > 0) { idx--; render(); } }
});

render();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # silence request log

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/" or path == "":
            self._serve_html()
        elif path.startswith("/scans/"):
            fname = path[len("/scans/"):]
            self._serve_file(SCANS_DIR / fname, "image/jpeg")
        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        if urlparse(self.path).path == "/tag":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            tags = load_tags()
            tags[body["page"]] = body["tag"]
            save_tags(tags)
            tagged = len(tags)
            remaining = len(PAGES) - tagged
            print(f"\r  {tagged}/{len(PAGES)} tagged  ({remaining} remaining)   ",
                  end="", flush=True)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
        else:
            self.send_response(404); self.end_headers()

    def _serve_html(self):
        tags = load_tags()
        html = HTML.replace("__PAGES_JSON__", json.dumps(PAGES))
        html = html.replace("__TAGS_JSON__", json.dumps(tags))
        data = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_file(self, path: Path, mime: str):
        if not path.exists():
            self.send_response(404); self.end_headers(); return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    os.chdir(REPO)
    print(f"Review server: http://localhost:{PORT}")
    print(f"Tags file:     {TAGS_PATH.relative_to(REPO)}")
    print(f"Pages:         {len(PAGES)}")
    print(f"\nKeyboard shortcuts:  H = Hebrew only  |  M = Mixed  |  U = Hungarian only  |  S = Skip")
    print(f"Tags saved live — you can quit and resume any time.\n")
    httpd = HTTPServer(("localhost", PORT), Handler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        tags = load_tags()
        print(f"\n\nStopped. {len(tags)}/{len(PAGES)} pages tagged.")
        print(f"Tags at: {TAGS_PATH}")
