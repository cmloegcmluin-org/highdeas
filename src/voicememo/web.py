"""Local Flask app for reviewing, editing, and routing memos."""
from flask import Flask, redirect, render_template_string, request, send_from_directory

# Inline, self-contained brand icons for the route toggle (no external assets).
NOTESNOOK_SVG = (
    '<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
    '<rect x="4" y="2.5" width="16" height="19" rx="3" fill="#0a9f79"/>'
    '<path d="M7.5 8h9M7.5 12h9M7.5 16h6" stroke="#fff" stroke-width="1.7" stroke-linecap="round"/>'
    "</svg>"
)
DRIVE_SVG = (
    '<svg viewBox="0 0 87.3 78" xmlns="http://www.w3.org/2000/svg">'
    '<path d="m6.6 66.85 3.85 6.65c.8 1.4 1.95 2.5 3.3 3.3l13.75-23.8h-27.5c0 1.55.4 3.1 1.2 4.5z" fill="#0066da"/>'
    '<path d="m43.65 25-13.75-23.8c-1.35.8-2.5 1.9-3.3 3.3l-25.4 44a9.06 9.06 0 0 0 -1.2 4.5h27.5z" fill="#00ac47"/>'
    '<path d="m73.55 76.8c1.35-.8 2.5-1.9 3.3-3.3l1.6-2.75 7.65-13.25c.8-1.4 1.2-2.95 1.2-4.5h-27.502l5.852 11.5z" fill="#ea4335"/>'
    '<path d="m43.65 25 13.75-23.8c-1.35-.8-2.9-1.2-4.5-1.2h-18.5c-1.6 0-3.15.45-4.5 1.2z" fill="#00832d"/>'
    '<path d="m59.8 53h-32.3l-13.75 23.8c1.35.8 2.9 1.2 4.5 1.2h50.8c1.6 0 3.15-.45 4.5-1.2z" fill="#2684fc"/>'
    '<path d="m73.4 26.5-12.7-22c-.8-1.4-1.95-2.5-3.3-3.3l-13.75 23.8 16.15 28h27.45c0-1.55-.4-3.1-1.2-4.5z" fill="#ffba00"/>'
    "</svg>"
)

INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Voice Memos to Review</title>
<style>
  :root { color-scheme: light dark; }
  body { font-family: -apple-system, "Segoe UI", system-ui, sans-serif; max-width: 1200px;
         margin: 0 auto; padding: 24px; line-height: 1.45; }
  h1 { font-size: 1.35rem; }
  .empty { opacity: .7; padding: 48px 0; text-align: center; }
  .grid { display: grid; grid-template-columns: 260px minmax(240px, 1fr) 170px 100px 104px;
          gap: 16px 18px; align-items: start; }
  .grid .head { font-size: .7rem; text-transform: uppercase; letter-spacing: .04em; opacity: .55;
                padding-bottom: 4px; border-bottom: 1px solid rgba(128,128,128,.25); }
  form.memo { display: contents; }
  .memo audio { width: 100%; }
  .memo textarea, .memo input[type=text] {
    width: 100%; box-sizing: border-box; padding: 8px; font: inherit;
    border: 1px solid rgba(128,128,128,.4); border-radius: 8px; background: transparent; color: inherit; }
  .memo textarea { min-height: 84px; resize: vertical; }
  .memo button { font: inherit; padding: 9px 0; width: 100%; border-radius: 8px; border: none;
                 background: #3b82f6; color: #fff; cursor: pointer; }
  .toggle { display: inline-flex; align-items: center; gap: 6px; cursor: pointer; }
  .toggle input { position: absolute; width: 0; height: 0; opacity: 0; }
  .toggle .ic { width: 18px; height: 18px; opacity: .35; transition: opacity .15s; }
  .toggle .ic svg { width: 100%; height: 100%; display: block; }
  .toggle .ns { opacity: 1; }
  .toggle input:checked ~ .ns { opacity: .35; }
  .toggle input:checked ~ .dr { opacity: 1; }
  .toggle .track { position: relative; flex: none; width: 40px; height: 22px; border-radius: 999px;
                   background: rgba(128,128,128,.4); transition: background .15s; }
  .toggle .track::after { content: ""; position: absolute; top: 3px; left: 3px; width: 16px; height: 16px;
                          border-radius: 50%; background: #fff; box-shadow: 0 1px 2px rgba(0,0,0,.35); transition: transform .15s; }
  .toggle input:checked ~ .track { background: #2684fc; }
  .toggle input:checked ~ .track::after { transform: translateX(18px); }
</style>
</head>
<body>
  <h1>Voice memos to review — {{ memos|length }} pending</h1>
  {% if not memos %}
    <p class="empty">Nothing to review. Record a memo and it'll show up here.</p>
  {% else %}
  <div class="grid">
    <div class="head">Audio</div>
    <div class="head">Transcript</div>
    <div class="head">Name</div>
    <div class="head">Route</div>
    <div class="head"></div>
    {% for m in memos %}
    <form class="memo" method="post" action="/submit/{{ m.audio_filename }}">
      <audio controls src="/audio/{{ m.audio_filename }}"></audio>
      <textarea name="transcript" aria-label="Transcript">{{ m.transcript }}</textarea>
      <input type="text" name="name" value="{{ m.name }}" placeholder="Name…" autocomplete="off" aria-label="Name">
      <label class="toggle" title="Left = Notesnook, right = Google Drive">
        <input type="checkbox" name="route" value="drive" {{ 'checked' if m.route == 'drive' }}>
        <span class="ic ns" aria-label="Notesnook">""" + NOTESNOOK_SVG + """</span>
        <span class="track"></span>
        <span class="ic dr" aria-label="Google Drive">""" + DRIVE_SVG + """</span>
      </label>
      <button type="submit">Submit</button>
    </form>
    {% endfor %}
  </div>
  {% endif %}
</body>
</html>
"""


def create_app(service, inbox_dir):
    app = Flask(__name__)

    @app.get("/")
    def index():
        service.refresh()
        return render_template_string(INDEX_HTML, memos=service.pending())

    @app.get("/audio/<path:filename>")
    def audio(filename):
        return send_from_directory(inbox_dir, filename)

    @app.post("/submit/<path:filename>")
    def submit(filename):
        service.edit(
            filename,
            name=request.form["name"],
            transcript=request.form["transcript"],
            route=request.form.get("route", "notesnook"),
        )
        service.submit(filename)
        return redirect("/")

    return app
