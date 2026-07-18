"""Names read out of a Google Sheet, so the list keeps up as the sheet changes.

Some of the words a transcript most needs are already written down somewhere else — a
column of people's names that gains a row most weeks. Keeping the same list twice, by
hand, is how it goes stale, so this reads that column instead.

Read as a service account rather than as a person: an app nobody is sitting at can't
work a consent screen, and an unattended OAuth token would expire in a week."""
import json
import re
import time
from pathlib import Path
from urllib.parse import quote

# The id inside a spreadsheet's own address, which is what there is to hand.
_IN_LINK = re.compile(r"/spreadsheets/d/([^/?#]+)")
_VALUES = "https://sheets.googleapis.com/v4/spreadsheets/{sheet}/values/{cells}"
# All this ever does is read one column, and the key it reads with carries a whole
# account, so it asks for the narrowest scope Google offers on a spreadsheet.
READ_ONLY = "https://www.googleapis.com/auth/spreadsheets.readonly"
# The characters A1 notation is written in — "'Sheet 2'!C2:C" — which the API expects to
# reach it as they were written. Everything else (a space, most of all) is escaped.
_A1 = ":!$'"
# A name this short is an initial standing in for one, and correcting toward it would
# rewrite half of ordinary speech.
_SHORTEST = 3


def spreadsheet_id(sheet):
    """The id of the spreadsheet `sheet` names — given either the id itself or the link
    the sheet was open at when it was copied."""
    found = _IN_LINK.search(sheet)
    return found.group(1) if found else sheet.strip()


def authorized_session(key_path, *, credentials=None, session=None):
    """A requests session that signs each call as the service account whose key sits at
    `key_path` — the account the sheet is shared with. Nothing here is interactive: the
    key is the whole credential, which is what lets an unattended app read the sheet."""
    credentials = credentials or _service_account_credentials
    session = session or _authorized_session
    return session(credentials(str(key_path), [READ_ONLY]))


def _service_account_credentials(key_path, scopes):
    from google.oauth2 import service_account

    return service_account.Credentials.from_service_account_file(key_path, scopes=scopes)


def _authorized_session(credentials):
    from google.auth.transport.requests import AuthorizedSession

    return AuthorizedSession(credentials)


def fetch_names(session, *, spreadsheet, cell_range, timeout=10):
    """The names in `cell_range` of `spreadsheet`, read over an authorized session."""
    url = _VALUES.format(sheet=quote(spreadsheet, safe=""),
                         cells=quote(cell_range, safe=_A1))
    response = session.get(url, params={"majorDimension": "COLUMNS"}, timeout=timeout)
    response.raise_for_status()
    return names_in(response.json().get("values", []))


def names_in(values):
    """The terms in a column of cells, as the Sheets API hands it back — one column, or
    nothing at all when the range holds no values."""
    found = {}
    for cell in values[0] if values else ():
        for name in _names_of(cell):
            if len(name) >= _SHORTEST:
                found[name] = None  # in the order the sheet has them, each name once
    return tuple(found)


def _names_of(cell):
    """Every name one cell holds. A row often names a person more than one way — two
    names either side of a slash, or a short form inside brackets — and any of them
    might be the one that gets spoken."""
    for part in cell.split("/"):
        part = part.strip()
        if "(" in part:
            yield part.replace("(", "").replace(")", "").strip()
            yield part[:part.index("(")].strip()
        elif part:
            yield part


class SheetNames:
    """The sheet's names, kept current without a round trip per recording.

    Every transcription asks for the terms, and memos arrive in bursts, so the sheet is
    read at most once every `ttl` seconds and the answer held between times."""

    def __init__(self, read, *, cache, ttl=600, clock=time.monotonic):
        self._read = read
        self._cache = Path(cache)
        self._ttl = ttl
        self._clock = clock
        self._names = _remembered(self._cache)
        self._read_at = None

    def __call__(self):
        if self._read_at is None or self._clock() - self._read_at >= self._ttl:
            # Stamped whatever happens: an unreachable sheet must not put a fresh
            # timeout in front of every recording for as long as the machine is off
            # the network.
            self._read_at = self._clock()
            try:
                self._names = tuple(self._read())
                _remember(self._cache, self._names)
            except Exception as exc:  # noqa: BLE001 — a stale name beats a lost memo
                print(f"Highdeas: keeping the names last read from the sheet ({exc}).")
        return self._names


def _remembered(cache):
    """The names last read from the sheet, so a machine that boots away from the
    network still knows them. Anything unreadable simply means none yet."""
    try:
        return tuple(json.loads(cache.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return ()


def _remember(cache, names):
    cache.write_text(json.dumps(list(names)), encoding="utf-8")
