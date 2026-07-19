from pathlib import Path

import pytest

from highdeas.routers import (
    AsanaRouter, ClaudeRouter, DriveMusicRouter, NotesnookRouter, Router,
    parse_asana_parents, read_asana_tokens, write_docx,
)
from highdeas.store import Memo


class RecordingRouter:
    def __init__(self):
        self.routed = []

    def route(self, memo):
        self.routed.append(memo.audio_filename)


class FakeResponse:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._body


class FakePost:
    def __init__(self, status_code=200, body=None):
        self.calls = []
        self._status_code = status_code
        self._body = body

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse(self._status_code, self._body)


def test_notesnook_router_posts_title_and_html_body():
    post = FakePost()
    router = NotesnookRouter("MY_KEY", post=post)

    router.route(Memo(audio_filename="a.m4a", name="Grocery idea", transcript="buy milk\nand eggs"))

    url, kwargs = post.calls[0]
    assert url == "https://inbox.notesnook.com/"
    assert kwargs["headers"] == {"Authorization": "MY_KEY", "Content-Type": "application/json"}
    body = kwargs["json"]
    assert body["title"] == "Grocery idea"
    assert body["type"] == "note"
    assert body["source"] == "highdeas"
    assert body["version"] == 1
    assert body["content"] == {"type": "html", "data": "<p>buy milk</p><p>and eggs</p>"}


def test_notesnook_router_turns_markdown_list_lines_into_real_html_lists():
    # A note is stored as plain text, so a list is just its Markdown line. Notesnook
    # takes HTML, so the lines become real <ul>/<ol> rather than arriving as literal
    # "- " and "1. " prefixes inside paragraphs.
    post = FakePost()

    NotesnookRouter("K", post=post).route(Memo(
        audio_filename="a.m4a", name="Plan",
        transcript="Shopping:\n- milk\n- eggs\nThen:\n1. bake\n2) eat",
    ))

    assert post.calls[0][1]["json"]["content"]["data"] == (
        "<p>Shopping:</p><ul><li>milk</li><li>eggs</li></ul>"
        "<p>Then:</p><ol><li>bake</li><li>eat</li></ol>"
    )


def test_notesnook_router_escapes_list_items():
    post = FakePost()

    NotesnookRouter("K", post=post).route(Memo(audio_filename="a.m4a", name="X", transcript="- <b>hi</b>"))

    assert post.calls[0][1]["json"]["content"]["data"] == "<ul><li>&lt;b&gt;hi&lt;/b&gt;</li></ul>"


def test_write_docx_styles_list_lines_as_word_lists(tmp_path):
    # The Drive .docx gets the same lists, as Word's own List Bullet / List Number
    # styles — not paragraphs that happen to start with "- ".
    from docx import Document

    write_docx(tmp_path / "note.docx", "Intro\n- milk\n1. bake")

    paragraphs = [(p.text, p.style.name) for p in Document(str(tmp_path / "note.docx")).paragraphs]
    assert paragraphs == [("Intro", "Normal"), ("milk", "List Bullet"), ("bake", "List Number")]


def test_notesnook_router_titles_unnamed_memo_with_its_recording_time():
    post = FakePost()

    NotesnookRouter("K", post=post).route(
        Memo(audio_filename="a.m4a", name="", transcript="hi", recorded_at="2026-07-07T15:45:00")
    )

    # Notesnook's own "Note $date$ $time$" style, but for when the memo was recorded,
    # and to the second so two memos from the same minute don't collide.
    assert post.calls[0][1]["json"]["title"] == "Note 2026-07-07 3:45:00 PM"


def test_notesnook_router_falls_back_to_scan_time_when_recording_time_unknown():
    post = FakePost()

    NotesnookRouter("K", post=post).route(
        Memo(audio_filename="a.m4a", name="", recorded_at="", created_at="2026-07-07T09:05:00")
    )

    assert post.calls[0][1]["json"]["title"] == "Note 2026-07-07 9:05:00 AM"


def test_notesnook_router_gives_two_same_minute_memos_distinct_titles():
    # Two unnamed memos recorded in the same minute must not share a title: same-title
    # notes collapse to one in the inbox, so a minute-precision auto-title silently drops
    # every second recording made within a minute. Seconds keep them distinct.
    post = FakePost()
    router = NotesnookRouter("K", post=post)

    router.route(Memo(audio_filename="a.m4a", name="", recorded_at="2026-07-08T10:45:02"))
    router.route(Memo(audio_filename="b.m4a", name="", recorded_at="2026-07-08T10:45:45"))

    assert post.calls[0][1]["json"]["title"] != post.calls[1][1]["json"]["title"]


def test_notesnook_router_never_sends_an_empty_title():
    # The Inbox API rejects a blank title (title: z.string().min(1)), so an
    # unnamed memo with no timestamps must still get a non-empty title.
    post = FakePost()

    NotesnookRouter("K", post=post).route(Memo(audio_filename="a.m4a", name=""))

    assert post.calls[0][1]["json"]["title"]


def test_notesnook_router_raises_on_error_response():
    post = FakePost(status_code=403)

    with pytest.raises(RuntimeError):
        NotesnookRouter("K", post=post).route(Memo(audio_filename="a.m4a", name="X", transcript="y"))


def test_router_dispatches_to_notesnook_by_default():
    notesnook, drive = RecordingRouter(), RecordingRouter()

    Router(notesnook=notesnook, drive=drive)(Memo(audio_filename="a.m4a", route="notesnook"))

    assert notesnook.routed == ["a.m4a"]
    assert drive.routed == []


def test_router_dispatches_to_drive_when_selected():
    notesnook, drive = RecordingRouter(), RecordingRouter()

    Router(notesnook=notesnook, drive=drive)(Memo(audio_filename="a.m4a", route="drive"))

    assert drive.routed == ["a.m4a"]
    assert notesnook.routed == []


def test_router_dispatches_to_claude_when_selected():
    notesnook, claude = RecordingRouter(), RecordingRouter()

    Router(notesnook=notesnook, claude=claude)(Memo(audio_filename="a.m4a", route="claude"))

    assert claude.routed == ["a.m4a"]
    assert notesnook.routed == []


def test_router_skips_drive_when_not_configured():
    notesnook = RecordingRouter()

    Router(notesnook=notesnook)(Memo(audio_filename="a.m4a", route="drive"))

    assert notesnook.routed == []


def test_router_dispatches_to_asana_and_returns_its_outcome():
    # A router may report fields for the store to persist (Asana reports the created
    # task's permalink); the dispatcher must pass that outcome through to the service.
    notesnook = RecordingRouter()

    class LinkingRouter:
        def route(self, memo):
            return {"asana_url": "https://app.asana.com/0/0/9/f"}

    outcome = Router(notesnook=notesnook, asana=LinkingRouter())(
        Memo(audio_filename="a.m4a", route="asana"))

    assert outcome == {"asana_url": "https://app.asana.com/0/0/9/f"}
    assert notesnook.routed == []


def test_asana_router_creates_a_subtask_under_the_memos_chosen_parent():
    post = FakePost(body={"data": {"gid": "42", "permalink_url": "https://app.asana.com/0/0/42/f"}})
    router = AsanaRouter({"": "PAT"}, default_parent="111", post=post)

    outcome = router.route(Memo(audio_filename="a.m4a", name="Bassline idea",
                                transcript="dum dum da dum", route="asana", asana_parent="222"))

    url, kwargs = post.calls[0]
    # The memo's own chosen parent wins over the configured default.
    assert url == "https://app.asana.com/api/1.0/tasks/222/subtasks"
    assert kwargs["headers"] == {"Authorization": "Bearer PAT", "Content-Type": "application/json"}
    # Ask Asana to return the created task's permalink so the bin can link to it.
    assert kwargs["params"] == {"opt_fields": "permalink_url"}
    # Only the text travels: the name and transcript, never the audio.
    assert kwargs["json"] == {"data": {"name": "Bassline idea", "notes": "dum dum da dum"}}
    assert outcome == {"asana_url": "https://app.asana.com/0/0/42/f"}


def test_asana_router_falls_back_to_the_default_parent_when_none_chosen():
    # A memo submitted before its dropdown was ever touched has no stored parent;
    # it lands under the first configured task rather than failing.
    post = FakePost(body={"data": {}})

    AsanaRouter({"": "PAT"}, default_parent="111", post=post).route(
        Memo(audio_filename="a.m4a", name="X", transcript="y", route="asana"))

    assert post.calls[0][0] == "https://app.asana.com/api/1.0/tasks/111/subtasks"


def test_asana_router_opens_a_parent_with_the_token_of_the_account_it_names():
    # Two Asana accounts, one dropdown: a parent written "account:gid" is created
    # under that account's own token, so the second account's tasks sit beside the
    # first's with nothing in the UI to say they are elsewhere.
    post = FakePost(body={"data": {}})
    router = AsanaRouter({"": "MINE", "WORK": "THEIRS"}, default_parent="111", post=post)

    router.route(Memo(audio_filename="a.m4a", name="X", transcript="y",
                      route="asana", asana_parent="WORK:333"))

    url, kwargs = post.calls[0]
    assert url == "https://app.asana.com/api/1.0/tasks/333/subtasks"
    assert kwargs["headers"]["Authorization"] == "Bearer THEIRS"


def test_asana_router_explains_missing_setup_instead_of_calling_asana():
    # An unset token or an empty parent list would otherwise surface as an opaque
    # Asana 401/404; name the .env variable to fix instead, and never hit the wire.
    post = FakePost()

    with pytest.raises(RuntimeError, match="ASANA_ACCESS_TOKEN"):
        AsanaRouter({"": ""}, default_parent="111", post=post).route(
            Memo(audio_filename="a.m4a", route="asana", asana_parent="222"))
    with pytest.raises(RuntimeError, match="ASANA_PARENT_TASKS"):
        AsanaRouter({"": "PAT"}, post=post).route(Memo(audio_filename="a.m4a", route="asana"))
    assert post.calls == []


def test_asana_router_names_unnamed_memo_by_its_transcript():
    # With nothing but spoken words, the transcript becomes the task's name so the
    # note reads at a glance in Asana instead of hiding under a generic date title.
    # It moves into the name, leaving the notes empty rather than repeating itself.
    post = FakePost(body={"data": {}})

    AsanaRouter({"": "PAT"}, default_parent="1", post=post).route(
        Memo(audio_filename="a.m4a", name="", transcript="call the plumber back",
             recorded_at="2026-07-07T15:45:00", route="asana"))

    assert post.calls[0][1]["json"]["data"] == {"name": "call the plumber back", "notes": ""}


def test_asana_router_titles_an_empty_memo_with_its_recording_time():
    # No name and no transcript — a failed or silent capture — still needs a title;
    # fall back to the recording-time convention shared with Notesnook.
    post = FakePost(body={"data": {}})

    AsanaRouter({"": "PAT"}, default_parent="1", post=post).route(
        Memo(audio_filename="a.m4a", name="", transcript="",
             recorded_at="2026-07-07T15:45:00", route="asana"))

    assert post.calls[0][1]["json"]["data"]["name"] == "Note 2026-07-07 3:45:00 PM"


def test_asana_router_raises_on_error_response():
    post = FakePost(status_code=403)

    with pytest.raises(RuntimeError):
        AsanaRouter({"": "PAT"}, default_parent="1", post=post).route(
            Memo(audio_filename="a.m4a", name="X", transcript="y", route="asana"))


def test_read_asana_tokens_finds_one_token_per_account_the_dropdown_offers():
    # The second account's token lives under its own name, so both accounts' tasks
    # can sit in one dropdown. Only the accounts actually offered are looked for.
    env = {"ASANA_ACCESS_TOKEN": "MINE", "ASANA_ACCESS_TOKEN_WORK": "THEIRS",
           "ASANA_ACCESS_TOKEN_UNUSED": "NOBODYS"}

    tokens = read_asana_tokens(parse_asana_parents("111=Songs;WORK:333=Work backlog"), env)

    assert tokens == {"": "MINE", "WORK": "THEIRS"}


def test_read_asana_tokens_reads_an_account_marker_however_it_was_written():
    # Environment lookups are case-sensitive on the Mac and not on Windows, so a
    # lowercased marker would submit fine at one desk and 401 at the other. The
    # marker names the variable, and variables are upper case.
    env = {"ASANA_ACCESS_TOKEN": "MINE", "ASANA_ACCESS_TOKEN_WORK": "THEIRS"}

    tokens = read_asana_tokens(parse_asana_parents("work:333=Work backlog"), env)

    assert tokens == {"": "MINE", "work": "THEIRS"}


def test_read_asana_tokens_always_looks_for_the_default_account():
    # Nothing configured yet still asks for the unsuffixed token, so the router can
    # name that variable when a submit finds it missing.
    assert read_asana_tokens([], {}) == {"": ""}


def test_parse_asana_parents_reads_gid_label_pairs():
    # The .env format: "task_gid=Label" pairs, ";"-separated, whitespace-tolerant.
    # Order is kept — the first pair is the default parent and leads the dropdown.
    raw = " 1200000000000001 = Song ideas ;1200000000000002=App ideas; "

    assert parse_asana_parents(raw) == [
        ("1200000000000001", "Song ideas"),
        ("1200000000000002", "App ideas"),
    ]


def test_parse_asana_parents_handles_missing_or_bare_config():
    assert parse_asana_parents("") == []
    assert parse_asana_parents(None) == []
    # A bare gid with no "=Label" still works, labelled by its gid.
    assert parse_asana_parents("1200000000000001") == [("1200000000000001", "1200000000000001")]


def test_claude_router_opens_a_code_session_through_the_deep_link_handler():
    # The Code pane answers to claude://, which only the OS handler can open — never
    # the browser, which would try to navigate to the scheme instead.
    browser, deep = [], []
    router = ClaudeRouter(open_browser=browser.append, open_deep_link=deep.append,
                          folder=r"C:\Users\Douglas\workspace\highdeas")

    router.route(Memo(audio_filename="a.m4a", route="claude", claude_surface="code",
                      transcript="show how many notes a group folded in"))

    assert browser == []
    assert deep == ["claude://code/new?q=show%20how%20many%20notes%20a%20group%20folded%20in"
                    "&folder=C%3A%5CUsers%5CDouglas%5Cworkspace%5Chighdeas"]


def test_claude_router_opens_a_chat_in_the_browser_at_its_chosen_model():
    # A chat is an ordinary https link, so it goes through the browser launcher — the
    # one that picks the Chrome profile Claude is signed into.
    browser, deep = [], []
    router = ClaudeRouter(open_browser=browser.append, open_deep_link=deep.append, folder="C:/repo")

    router.route(Memo(audio_filename="a.m4a", route="claude", claude_surface="chat",
                      claude_model="claude-sonnet-5", transcript="what rhymes with orange"))

    assert deep == []
    assert browser == ["https://claude.ai/new?q=what%20rhymes%20with%20orange"
                       "&model=claude-sonnet-5"]


def test_claude_router_leaves_an_unchosen_model_out_of_the_link():
    # "model=" with nothing behind it is not the same as not naming a model, so an
    # empty choice drops the parameter rather than sending it blank.
    browser = []
    router = ClaudeRouter(open_browser=browser.append, open_deep_link=[].append, folder="C:/repo")

    router.route(Memo(audio_filename="a.m4a", route="claude", claude_surface="chat",
                      transcript="hello"))

    assert browser == ["https://claude.ai/new?q=hello"]


def test_claude_router_puts_a_notes_name_above_its_transcript_in_the_prompt():
    # A prompt is one block of text, so a named note leads with its name — the same
    # reading order the row and the editor give it.
    deep = []
    router = ClaudeRouter(open_browser=[].append, open_deep_link=deep.append, folder="C:/repo")

    router.route(Memo(audio_filename="a.m4a", route="claude", claude_surface="code",
                      name="Group badges", transcript="show the count"))

    assert "q=Group%20badges%0A%0Ashow%20the%20count&" in deep[0]


def test_drive_router_copies_audio_into_dated_folder_and_writes_doc(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    drive = tmp_path / "drive"
    drive.mkdir()
    (inbox / "voice-3.m4a").write_bytes(b"AUDIO")
    docs = []

    router = DriveMusicRouter(
        inbox, drive,
        today=lambda: "2026_07_07",
        write_doc=lambda path, text: docs.append((Path(path), text)),
    )
    router.route(Memo(audio_filename="voice-3.m4a", name="Korok Dance", transcript="la la la"))

    folder = drive / "_2026_07_07_NOT_YET_PROCESSED_MUSIC"
    assert (folder / "Korok Dance.m4a").read_bytes() == b"AUDIO"
    # The original stays in the inbox so the service also retires it to the local bin.
    assert (inbox / "voice-3.m4a").read_bytes() == b"AUDIO"
    assert docs == [(folder / "Korok Dance.docx", "la la la")]


def _drive_router(inbox, drive, **kwargs):
    inbox.mkdir(exist_ok=True)
    drive.mkdir(exist_ok=True)
    return DriveMusicRouter(inbox, drive, today=lambda: "2026_07_07",
                            write_doc=kwargs.get("write_doc", lambda path, text: None))


def test_drive_router_skips_doc_when_transcript_is_blank(tmp_path):
    (tmp_path / "inbox").mkdir()
    (tmp_path / "inbox" / "v.m4a").write_bytes(b"A")
    docs = []
    router = _drive_router(tmp_path / "inbox", tmp_path / "drive",
                           write_doc=lambda path, text: docs.append(path))

    router.route(Memo(audio_filename="v.m4a", name="Song", transcript="   "))

    assert docs == []
    assert (tmp_path / "drive" / "_2026_07_07_NOT_YET_PROCESSED_MUSIC" / "Song.m4a").exists()


def test_drive_router_sanitizes_illegal_filename_characters(tmp_path):
    (tmp_path / "inbox").mkdir()
    (tmp_path / "inbox" / "v.m4a").write_bytes(b"A")
    router = _drive_router(tmp_path / "inbox", tmp_path / "drive")

    router.route(Memo(audio_filename="v.m4a", name='Take 1/2: "final?"', transcript=""))

    assert (tmp_path / "drive" / "_2026_07_07_NOT_YET_PROCESSED_MUSIC" / "Take 12 final.m4a").exists()


def test_drive_router_falls_back_to_audio_stem_when_unnamed(tmp_path):
    (tmp_path / "inbox").mkdir()
    (tmp_path / "inbox" / "voice-5.m4a").write_bytes(b"A")
    router = _drive_router(tmp_path / "inbox", tmp_path / "drive")

    router.route(Memo(audio_filename="voice-5.m4a", name="", transcript=""))

    assert (tmp_path / "drive" / "_2026_07_07_NOT_YET_PROCESSED_MUSIC" / "voice-5.m4a").exists()
