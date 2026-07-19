"""Routers that hand a submitted memo to its chosen destination.

Three of them deliver it outright — Notesnook, Google Drive, Asana. The fourth
opens it in Claude as a prompt nobody has sent yet."""
import html
import re
import shutil
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlencode

import requests


# A note is stored as plain text, so a list is just its Markdown line — which is
# what the editor writes and reads back. Both destinations turn those lines into
# real lists: HTML for Notesnook, Word's list styles for a Drive .docx.
_BULLET = re.compile(r"^\s*[-*•]\s+(.*)$")
_NUMBER = re.compile(r"^\s*\d+[.)]\s+(.*)$")


def _list_item(line):
    """The item text and its list tag ("ul"/"ol"), or (None, None) for prose."""
    bullet = _BULLET.match(line)
    if bullet:
        return bullet.group(1).strip(), "ul"
    number = _NUMBER.match(line)
    if number:
        return number.group(1).strip(), "ol"
    return None, None


def _text_to_html(text):
    parts = []
    open_tag = None
    for line in text.split("\n"):
        item, tag = _list_item(line)
        if tag != open_tag:
            if open_tag:
                parts.append(f"</{open_tag}>")
            if tag:
                parts.append(f"<{tag}>")
            open_tag = tag
        if tag:
            parts.append(f"<li>{html.escape(item)}</li>")
        elif line.strip():
            parts.append(f"<p>{html.escape(line.strip())}</p>")
    if open_tag:
        parts.append(f"</{open_tag}>")
    return "".join(parts) or "<p></p>"


def _default_title(memo):
    """Name an unnamed memo the way Notesnook names untitled notes ("Note $date$
    $time$"), from when it happened: the moment it was recorded, or failing that
    the moment the app first saw it. Notesnook's Inbox API requires a non-empty
    title, so this always returns one even when neither time is known.

    The time is to the second, not the minute: two unnamed memos recorded in the
    same minute would otherwise share a title, and same-titled notes collapse to one
    in the inbox — silently dropping every second recording made within a minute."""
    try:
        made = datetime.fromisoformat(memo.recorded_at or memo.created_at)
    except (TypeError, ValueError):
        return "Voice note"
    hour = made.hour % 12 or 12
    meridiem = "AM" if made.hour < 12 else "PM"
    return f"Note {made:%Y-%m-%d} {hour}:{made:%M}:{made:%S} {meridiem}"


class NotesnookRouter:
    """Create a note via the Notesnook Inbox API (POST https://inbox.notesnook.com/)."""

    ENDPOINT = "https://inbox.notesnook.com/"

    def __init__(self, api_key, *, source="highdeas", post=requests.post):
        self._api_key = api_key
        self._source = source
        self._post = post

    def route(self, memo):
        response = self._post(
            self.ENDPOINT,
            headers={"Authorization": self._api_key, "Content-Type": "application/json"},
            json={
                "title": memo.name or _default_title(memo),
                "type": "note",
                "source": self._source,
                "version": 1,
                "content": {"type": "html", "data": _text_to_html(memo.transcript)},
            },
            timeout=30,
        )
        response.raise_for_status()


def parse_asana_parents(raw):
    """Read ASANA_PARENT_TASKS — ";"-separated "task_gid=Label" pairs — into an
    ordered list of (parent, label). The first pair is the default parent and leads
    the inbox dropdown. A pair without "=Label" is labelled by the task itself.

    A gid may be prefixed "ACCOUNT:" to say which Asana account holds that task, so
    a second account's tasks join the same dropdown with nothing to mark them out
    (see _account_and_gid). The prefix travels with the gid as one value: it is what
    the dropdown offers and what the memo remembers being bound to."""
    parents = []
    for pair in (raw or "").split(";"):
        parent, _, label = pair.partition("=")
        parent, label = parent.strip(), label.strip()
        if parent:
            parents.append((parent, label or parent))
    return parents


def _account_and_gid(parent):
    """Split a dropdown value into the account holding the task and the task's gid.
    "WORK:333" is task 333 in the "WORK" account; a bare "333" is the account the
    app has always had, whose token is the unsuffixed ASANA_ACCESS_TOKEN."""
    account, marked, gid = parent.partition(":")
    return (account, gid) if marked else ("", parent)


def _asana_token_variable(account):
    """The .env variable holding an account's token — ASANA_ACCESS_TOKEN for the
    unnamed default, ASANA_ACCESS_TOKEN_WORK for "work".

    Upper-cased because that is what the marker names: a variable. Environment
    lookups are case-sensitive on the Mac and not on Windows, so a marker taken
    literally would submit fine at one desk and 401 at the other."""
    return f"ASANA_ACCESS_TOKEN_{account.upper()}" if account else "ASANA_ACCESS_TOKEN"


def read_asana_tokens(parents, env):
    """The access token for every account the offered parents name, read from `env`.
    Each account is one more personal access token; only the accounts actually on
    the dropdown are looked for, so a second one costs nothing until a task names
    it. The default account is always among them, so a submit with nothing
    configured can still name the variable to fill in."""
    accounts = {""} | {_account_and_gid(parent)[0] for parent, _ in parents}
    return {account: env.get(_asana_token_variable(account), "") for account in accounts}


class AsanaRouter:
    """Create the memo's text as a subtask of its chosen Asana parent task
    (POST /tasks/{gid}/subtasks). Only the text goes to Asana — the note's
    name and transcript; the recording itself stays local and retires to the
    bin like every other route. Reports the created task's permalink for the
    memo's record, so the bin icon can open the task.

    Holds one token per Asana account, since a parent task names the account it
    belongs to: two accounts are two tokens behind one dropdown."""

    ENDPOINT = "https://app.asana.com/api/1.0/tasks/{gid}/subtasks"

    def __init__(self, tokens, *, default_parent="", post=requests.post):
        self._tokens = tokens
        self._default_parent = default_parent
        self._post = post

    def route(self, memo):
        parent = memo.asana_parent or self._default_parent
        if not parent:
            raise RuntimeError("No Asana parent task configured — put ASANA_PARENT_TASKS in .env.")
        account, gid = _account_and_gid(parent)
        token = self._tokens.get(account, "")
        if not token:
            raise RuntimeError("Asana access token not set — put "
                               f"{_asana_token_variable(account)} in .env.")
        # A named memo keeps its transcript as the task's notes. An unnamed one has
        # only its transcript, so that becomes the name — a readable task rather than
        # a generic date title — and the notes are left empty rather than repeating it.
        if memo.name:
            name, notes = memo.name, memo.transcript
        else:
            name = memo.transcript or _default_title(memo)
            notes = ""
        response = self._post(
            self.ENDPOINT.format(gid=gid),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            params={"opt_fields": "permalink_url"},
            json={"data": {"name": name, "notes": notes}},
            timeout=30,
        )
        response.raise_for_status()
        return {"asana_url": response.json().get("data", {}).get("permalink_url", "")}


def _link(base, **params):
    """`base` with its non-empty `params` as a query string, spaces as %20 rather
    than "+". An empty value is left out entirely: "model=" with nothing behind it
    is a request for a model named "", not the absence of a request."""
    given = {name: value for name, value in params.items() if value}
    return f"{base}?{urlencode(given, quote_via=quote)}"


class ClaudeRouter:
    """Open the note as an unsent prompt in a new Claude session.

    Nothing is sent: both surfaces fill the composer and stop, so the memo leaves
    Highdeas as a question waiting to be read rather than as a delivered note."""

    def __init__(self, open_browser, open_deep_link, *, folder=""):
        self._open_browser = open_browser
        self._open_deep_link = open_deep_link
        self._folder = folder

    def route(self, memo):
        prompt = "\n\n".join(part for part in (memo.name, memo.transcript) if part)
        if memo.claude_surface == "chat":
            self._open_browser(_link("https://claude.ai/new", q=prompt,
                                     model=memo.claude_model))
        else:
            self._open_deep_link(_link("claude://code/new", q=prompt,
                                       folder=self._folder))


class Router:
    """Dispatch a memo to the router for its chosen route (Notesnook by default),
    passing through whatever fields that router reports for the store to persist
    (e.g. Asana's link to the created task)."""

    def __init__(self, notesnook, drive=None, asana=None, claude=None):
        self._routers = {"notesnook": notesnook, "drive": drive, "asana": asana,
                         "claude": claude}

    def __call__(self, memo):
        router = self._routers.get(memo.route, self._routers["notesnook"])
        if router is not None:
            return router.route(memo)
        return None


def _today():
    return datetime.now().strftime("%Y_%m_%d")


def _sanitize_filename(name):
    cleaned = re.sub(r'[<>:"/\\|?*]', "", name).strip()
    return cleaned or "untitled"


_LIST_STYLE = {"ul": "List Bullet", "ol": "List Number"}


def write_docx(path, text):
    from docx import Document

    document = Document()
    for line in text.split("\n"):
        item, tag = _list_item(line)
        if tag:
            document.add_paragraph(item, style=_LIST_STYLE[tag])
        else:
            document.add_paragraph(line)
    document.save(str(path))


class DriveMusicRouter:
    """Copy a music memo into a dated folder under the Drive base, with an optional doc.

    The original stays in the inbox so the service can also retire it to the local
    bin — the memo is then recoverable there for 90 days regardless of what happens
    to the Drive copy."""

    def __init__(self, inbox_dir, drive_base, *, today=_today, write_doc=write_docx, copy=shutil.copy2):
        self._inbox = Path(inbox_dir)
        self._base = Path(drive_base)
        self._today = today
        self._write_doc = write_doc
        self._copy = copy

    def route(self, memo):
        folder = self._base / f"_{self._today()}_NOT_YET_PROCESSED_MUSIC"
        folder.mkdir(parents=True, exist_ok=True)
        source = self._inbox / memo.audio_filename
        base = _sanitize_filename(memo.name or Path(memo.audio_filename).stem)
        self._copy(str(source), str(folder / (base + source.suffix)))
        if memo.transcript.strip():
            self._write_doc(folder / (base + ".docx"), memo.transcript)
