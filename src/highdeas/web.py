"""Local Flask app: the inbox and bin pages for editing and routing memos.

The pages themselves live in `templates/`, their behaviour in `static/`; this
module is the routes and nothing else.
"""
from urllib.parse import quote

from flask import Flask, redirect, render_template, request, send_from_directory


def _submitted_fields():
    """Editable field values shared by auto-save (/edit) and Submit (/submit)."""
    return {
        "name": request.form["name"],
        "transcript": request.form["transcript"],
        "route": request.form.get("route", "notesnook"),
    }


def create_app(service, inbox_dir, bin_dir, launch_drive=None):
    app = Flask(__name__)

    @app.get("/")
    def index():
        # No rescan here: the page must paint instantly from what's already stored.
        # The background catch-up transcribes waiting recordings and the /pending
        # poll streams them in, so the first frame never waits on the model.
        return render_template(
            "inbox.html", memos=service.pending(), incoming=service.has_incoming()
        )

    @app.get("/pending")
    def pending():
        """The inbox rows alone — polled by the open page to pick up recordings
        that arrive after load, so the app stays current without a manual reload."""
        service.refresh()
        return render_template("rows.html", memos=service.pending())

    @app.get("/audio/<path:filename>")
    def audio(filename):
        return send_from_directory(inbox_dir, filename)

    @app.post("/edit/<path:filename>")
    def edit(filename):
        service.edit(filename, **_submitted_fields())
        return ("", 204)

    @app.post("/submit/<path:filename>")
    def submit(filename):
        service.edit(filename, **_submitted_fields())
        try:
            service.submit(filename)
        except Exception as exc:  # noqa: BLE001 — any routing failure must reach the client
            # Routing failed (e.g. Notesnook rejected the key), so the memo is still
            # pending and its audio still in the inbox. Signal the failure instead of a
            # false 204 so the client keeps the row rather than hiding a note that never
            # sent — the "Submit all vanished everything but sent nothing" bug.
            return (f"Submit failed: {exc}", 502)
        return ("", 204)

    @app.post("/reorder")
    def reorder():
        """Persist the order a drag-and-drop left the inbox rows in, top to bottom."""
        service.reorder(request.form.getlist("order"))
        return ("", 204)

    @app.post("/delete/<path:filename>")
    def delete(filename):
        service.delete(filename)
        return ("", 204)

    @app.get("/bin")
    def bin_view():
        return render_template("bin.html", memos=service.binned())

    @app.get("/bin-audio/<path:filename>")
    def bin_audio(filename):
        return send_from_directory(bin_dir, filename)

    @app.post("/restore/<path:filename>")
    def restore(filename):
        service.restore(filename)
        return redirect("/bin")

    @app.post("/purge/<path:filename>")
    def purge(filename):
        service.purge(filename)
        return redirect("/bin")

    @app.post("/empty-bin")
    def empty_bin():
        service.empty_bin()
        return redirect("/bin")

    @app.post("/restore-all")
    def restore_all():
        service.restore_all()
        return redirect("/bin")

    @app.post("/open-drive")
    def open_drive():
        """Open a memo in Google Drive. A link can't choose which Chrome profile
        opens it, so the app launches Chrome itself (launch_drive) at a Drive search
        for the memo — the server builds the URL so only Drive can be opened."""
        if launch_drive is not None:
            launch_drive("https://drive.google.com/drive/u/0/search?q=" + quote(request.form.get("q", "")))
        return ("", 204)

    return app
