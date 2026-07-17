"""Relabel a transcript the speech model didn't hear as clean speech.

The ASR model is a speech recognizer, and it rarely just returns nothing. Hummed or
sung notes come back as filler — "Mm-hmm", "mm mm mm", "La la la" — and noise it can't
read comes back as a confident hallucination, often in another script entirely (a room
tone once transcribed as Cyrillic). Both used to reach the inbox verbatim.

So the raw text is read here before it's stored: an all-humming note becomes `[singing]`,
a run of humming inside speech is bracketed where it sits ("[singing] That was singing."),
and an empty or wrong-script result becomes `[unclear]`. Everything that reads as real
speech — the overwhelming majority — is handed back exactly as it came, untouched."""
import re
import unicodedata

SINGING = "[singing]"
UNCLEAR = "[unclear]"

# A voiced sound with no vowel — mm, hmm, hm, mhm, mmhmm. No English word is spelled
# from only m and h, so a whole token of them is unmistakably humming, even alone.
_HUM = re.compile(r"[mh]*m[mh]*")
# The syllables singing turns into when there are no words: "la la la", "doo doo",
# "da da da". Any real word among them is rare and, on its own, ambiguous (a lone
# "la" could be a place) — so a single one only counts inside a run (see below).
_SYLLABLE = re.compile(r"(?:(?:la|na|da|doo|dum|dee|dah|doot|tra|bum|dun)-?)+")
# How many humming tokens in a row it takes to read as a sung passage rather than a
# stray "mm" of thought. Below this, the tokens are left as the model heard them.
_RUN = 3


def mark_nonspeech(text):
    """`text` as a note should read: `[singing]`/`[unclear]` when the model heard no
    real speech, the same text back when it did."""
    core = text.strip()
    if not core or not any(c.isalnum() for c in core):
        return UNCLEAR
    if _wrong_script(core):
        return UNCLEAR
    tokens = core.split()
    filler = [_is_filler(t) for t in tokens]
    if all(filler) and (len(tokens) > 1 or _is_hum(tokens[0])):
        return SINGING
    return _bracket_runs(tokens, filler, text)


def _is_hum(token):
    core = _letters(token)
    return len(core) >= 2 and _HUM.fullmatch(core) is not None


def _is_filler(token):
    core = _letters(token)
    return len(core) >= 2 and (
        _HUM.fullmatch(core) is not None or _SYLLABLE.fullmatch(core) is not None)


def _letters(token):
    return "".join(c for c in token if c.isalpha()).lower()


def _bracket_runs(tokens, filler, original):
    """Replace each run of `_RUN`+ humming tokens with one `[singing]`, keeping the
    words around it. Returns `original` unchanged (whitespace and all) when no run is
    long enough — the common case, where nothing was humming."""
    out, i, changed = [], 0, False
    while i < len(tokens):
        run = i
        while run < len(tokens) and filler[run]:
            run += 1
        if run - i >= _RUN:
            out.append(SINGING)
            changed = True
            i = run
        else:
            out.append(tokens[i])
            i += 1
    return " ".join(out) if changed else original


def _wrong_script(text):
    """Whether most of the letters aren't Latin — the tell of a hallucination, since
    the recordings are spoken in English. Accented Latin (café, déjà) still counts as
    Latin; Cyrillic, CJK, Arabic, and the like do not."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    foreign = sum("LATIN" not in unicodedata.name(c, "") for c in letters)
    return foreign > len(letters) / 2
