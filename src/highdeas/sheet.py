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


def read_sources(path):
    """Every sheet the terms are read from, as `(link, cells)`.

    One per line, in a file beside the lexicon: the sheet's link, then the cells its
    names are in. That is the whole of adding a source — no setting, no release, and
    no restart — because there will be many of them, and they arrive one at a time.
    Blank lines and `#` comments are skipped, and so is a line that names no cells: a
    link on its own is a half-typed source, not a sheet to read entirely."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return ()
    sources = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Split once: everything after the link is the cells, spaces and all, since a
        # tab's name can hold them — "'Sheet 2'!A2:A".
        link, _, cells = line.partition(" ")
        if cells.strip():
            sources.append((link, cells.strip()))
    return tuple(sources)


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


class SheetTerms:
    """Every name in every sheet the sources file lists.

    The file is read afresh each time, so a source added to it is read from on the next
    recording; each sheet named in it keeps its own reader, and thus its own sense of
    when it was last asked."""

    def __init__(self, sources, *, read, cache, ttl=600, clock=time.monotonic):
        self._sources = Path(sources)
        self._read = read
        self._cache = cache
        self._ttl = ttl
        self._clock = clock
        self._sheets = {}

    def __call__(self):
        names = ()
        for link, cells in read_sources(self._sources):
            names += self._sheet(spreadsheet_id(link), cells)()
        return names

    def _sheet(self, spreadsheet, cells):
        """The reader for one sheet, made once and kept — a new one each recording
        would forget when it last asked, and ask again every time."""
        source = f"{spreadsheet} {cells}"
        if source not in self._sheets:
            self._sheets[source] = SheetNames(
                lambda: self._read(spreadsheet, cells), source=source,
                cache=self._cache, ttl=self._ttl, clock=self._clock)
        return self._sheets[source]


class SheetNames:
    """One sheet's names, kept current without a round trip per recording.

    Every transcription asks for the terms, and memos arrive in bursts, so the sheet is
    read at most once every `ttl` seconds and the answer held between times."""

    def __init__(self, read, *, source, cache, ttl=600, clock=time.monotonic):
        self._read = read
        self._source = source
        self._cache = cache
        self._ttl = ttl
        self._clock = clock
        self._names = cache.get(source)
        self._read_at = None

    def __call__(self):
        if self._read_at is None or self._clock() - self._read_at >= self._ttl:
            # Stamped whatever happens: an unreachable sheet must not put a fresh
            # timeout in front of every recording for as long as the machine is off
            # the network.
            self._read_at = self._clock()
            try:
                self._names = tuple(self._read())
                self._cache.put(self._source, self._names)
            except Exception as exc:  # noqa: BLE001 — a stale name beats a lost memo
                print(f"Highdeas: keeping the names last read from {self._source} ({exc}).")
        return self._names


class NameCache:
    """The names last read from each source, in one file beside the lexicon.

    A machine that boots away from the network still knows them, and — since the file
    sits in the folder the two machines share — one desk's read warms the other's."""

    def __init__(self, path):
        self._path = Path(path)

    def get(self, source):
        return tuple(self._all().get(source, ()))

    def put(self, source, names):
        remembered = self._all()
        remembered[source] = list(names)
        self._path.write_text(json.dumps(remembered, ensure_ascii=False, indent=1),
                              encoding="utf-8")

    def _all(self):
        """What is remembered, or nothing at all: an unreadable or foreign file is one
        cold read of every sheet, never a crash."""
        try:
            remembered = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return remembered if isinstance(remembered, dict) else {}
