from highdeas.sheet import (
    SheetNames,
    authorized_session,
    fetch_names,
    names_in,
    spreadsheet_id,
)


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class FakeSession:
    """The slice of an authorized requests session the fetch touches."""

    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse(self.payload)


def test_names_in_a_column_are_terms_to_correct_toward():
    # One column of a spreadsheet, as the Sheets API hands it back.
    assert names_in([["Marguerite", "Sasha", "Ilse"]]) == ("Marguerite", "Sasha", "Ilse")


def test_names_in_a_column_skip_its_gaps_and_its_one_letter_stand_ins():
    # A column has blanks in it, and rows where the name is a single initial. Two
    # letters is no name to correct toward — it would match half of ordinary speech.
    assert names_in([["Marguerite", "", "   ", "S", "Roxana"]]) == ("Marguerite", "Roxana")


def test_names_in_an_empty_column_are_no_names():
    # A range with nothing in it comes back with no column at all, not an empty one.
    assert names_in([]) == ()


def test_a_cell_holding_two_names_for_one_person_gives_both():
    # A row often carries two names for the same person — one either side of a slash,
    # or a short form in brackets. Either might be the one spoken, so both are terms.
    assert names_in([["Kiki / Kiara", "Sam(antha)"]]) == (
        "Kiki", "Kiara", "Samantha", "Sam")


def test_fetching_asks_the_api_for_the_one_column_of_the_sheet():
    session = FakeSession({"range": "A!C2:C", "values": [["Marguerite", "Roxana"]]})

    names = fetch_names(session, spreadsheet="SHEET_ID", cell_range="C2:C")

    assert names == ("Marguerite", "Roxana")
    url, kwargs = session.calls[0]
    assert url == "https://sheets.googleapis.com/v4/spreadsheets/SHEET_ID/values/C2:C"
    # A column, not the rows it would come back as by default.
    assert kwargs["params"]["majorDimension"] == "COLUMNS"


def test_fetching_escapes_a_range_that_names_a_tab_with_spaces_in_it():
    # "'Sheet 2'!C2:C" is a legal range and an illegal URL until it's quoted.
    session = FakeSession({"values": []})

    fetch_names(session, spreadsheet="ID", cell_range="'Sheet 2'!C2:C")

    assert session.calls[0][0].endswith("/values/'Sheet%202'!C2:C")


class FakeSheet:
    """A sheet that answers a fixed list, counting how often it is asked."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.asked = 0

    def __call__(self):
        self.asked += 1
        answer = self.answers[min(self.asked - 1, len(self.answers) - 1)]
        if isinstance(answer, Exception):
            raise answer
        return answer


def test_the_sheet_is_asked_once_and_then_left_alone_for_a_while(tmp_path):
    # Every recording asks for the terms, and most of them arrive in a burst. Asking
    # Google once per memo would put a network round trip in front of each one.
    now = [0]
    sheet = FakeSheet(("Marguerite",), ("Marguerite", "Roxana"))
    names = SheetNames(sheet, cache=tmp_path / "names.json", ttl=600,
                       clock=lambda: now[0])

    assert names() == ("Marguerite",)
    assert names() == ("Marguerite",)
    assert sheet.asked == 1

    now[0] = 700  # ...but it does go back, once the while is up

    assert names() == ("Marguerite", "Roxana")


def test_a_sheet_that_cannot_be_reached_leaves_the_names_it_last_had(tmp_path):
    # The MacBook spends its life off this network. A transcript arriving with a stale
    # name is nothing; a transcription that fails — or waits out a timeout — is a lot.
    now = [0]
    sheet = FakeSheet(("Marguerite",), OSError("no route to host"))
    names = SheetNames(sheet, cache=tmp_path / "names.json", ttl=600,
                       clock=lambda: now[0])
    assert names() == ("Marguerite",)

    now[0] = 700

    assert names() == ("Marguerite",)
    assert sheet.asked == 2

    now[0] = 800  # and a machine that stays offline isn't asked again every memo

    assert names() == ("Marguerite",)
    assert sheet.asked == 2


def test_the_names_outlive_the_app_so_a_cold_offline_machine_still_knows_them(tmp_path):
    # The names are kept beside the memo state, where the sync engine carries them:
    # this machine's read warms the other one, and a laptop that boots away from the
    # network transcribes against the last list either of them saw.
    cache = tmp_path / "names.json"
    SheetNames(FakeSheet(("Marguerite", "Roxana")), cache=cache, clock=lambda: 0)()

    cold = SheetNames(FakeSheet(OSError("offline")), cache=cache, clock=lambda: 0)

    assert cold() == ("Marguerite", "Roxana")


def test_the_session_signs_as_the_service_account_and_asks_only_to_read():
    # The key file carries a robot account's whole identity, and all this ever needs
    # is one column of one sheet — so it asks for the read-only scope and no other.
    made = {}

    def credentials(path, scopes):
        made.update(path=path, scopes=scopes)
        return "CREDENTIALS"

    session = authorized_session("C:/keys/highdeas.json", credentials=credentials,
                                 session=lambda creds: ("SESSION", creds))

    assert session == ("SESSION", "CREDENTIALS")
    assert made == {"path": "C:/keys/highdeas.json",
                    "scopes": ["https://www.googleapis.com/auth/spreadsheets.readonly"]}


def test_a_sheet_is_named_by_its_id_or_by_the_link_it_was_copied_from():
    # Nobody has the bare id to hand; what you have is the address bar.
    assert spreadsheet_id("1AbC_def-123") == "1AbC_def-123"
    assert spreadsheet_id(
        "https://docs.google.com/spreadsheets/d/1AbC_def-123/edit?usp=drivesdk"
    ) == "1AbC_def-123"
