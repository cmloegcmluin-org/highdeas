"""Local Flask app for reviewing, editing, and routing memos."""
from flask import Flask, redirect, render_template_string, request, send_from_directory

INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Voice Memos to Review</title>
<style>
  :root { color-scheme: light dark; }
  body { font-family: -apple-system, "Segoe UI", system-ui, sans-serif; max-width: 820px;
         margin: 0 auto; padding: 24px; line-height: 1.5; }
  h1 { font-size: 1.4rem; }
  .empty { opacity: .7; padding: 48px 0; text-align: center; }
  .memo { border: 1px solid rgba(128,128,128,.35); border-radius: 12px;
          padding: 16px; margin: 16px 0; }
  .memo audio { width: 100%; margin-bottom: 12px; }
  .memo label { display: block; font-size: .8rem; opacity: .7; margin: 10px 0 4px; }
  .memo input[type=text], .memo textarea {
    width: 100%; box-sizing: border-box; padding: 8px; font: inherit;
    border: 1px solid rgba(128,128,128,.4); border-radius: 8px; background: transparent; color: inherit; }
  .memo textarea { min-height: 92px; resize: vertical; }
  .row { display: flex; align-items: center; justify-content: space-between;
         gap: 12px; margin-top: 12px; flex-wrap: wrap; }
  .toggle label { display: inline-flex; align-items: center; gap: 5px; margin-right: 16px; font-size: .95rem; opacity: 1; }
  button { font: inherit; padding: 9px 20px; border-radius: 8px; border: none;
           background: #3b82f6; color: #fff; cursor: pointer; }
  .fname { font-size: .72rem; opacity: .5; margin-top: 10px; }
</style>
</head>
<body>
  <h1>Voice memos to review — {{ memos|length }} pending</h1>
  {% if not memos %}
    <p class="empty">Nothing to review. Record a memo and it'll show up here.</p>
  {% endif %}
  {% for m in memos %}
  <form class="memo" method="post" action="/submit/{{ m.audio_filename }}">
    <audio controls src="/audio/{{ m.audio_filename }}"></audio>
    <label>Name</label>
    <input type="text" name="name" value="{{ m.name }}" placeholder="Name this note…" autocomplete="off">
    <label>Transcript</label>
    <textarea name="transcript">{{ m.transcript }}</textarea>
    <div class="row">
      <span class="toggle">
        <label><input type="radio" name="route" value="notesnook" {{ 'checked' if m.route != 'drive' }}> 📝 Notesnook</label>
        <label><input type="radio" name="route" value="drive" {{ 'checked' if m.route == 'drive' }}> 🎵 Drive (music)</label>
      </span>
      <button type="submit">Submit</button>
    </div>
    <div class="fname">{{ m.audio_filename }}</div>
  </form>
  {% endfor %}
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
            route=request.form["route"],
        )
        service.submit(filename)
        return redirect("/")

    return app
