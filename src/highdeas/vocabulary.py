"""The names and terms a general-purpose speech model has never heard.

A coined name ("Highdeas"), the vocabulary of a field ("Sagittal notation",
"xenharmonic"), the people in someone's life: the model renders each as whatever
ordinary words sound closest — "high ideas", "sagital", a name spelled three ways
across three memos — and no amount of re-recording teaches it otherwise. Nor can it
be told what to expect: onnx-asr's Parakeet path exposes no hotword or contextual
biasing hook (its RecognizeOptions cover only Whisper/Canary language flags).

So the correcting happens after the decode. The words that came out are read against
a lexicon — a hand-kept file, one term per line — and each near-miss is swapped for
the term it missed."""
import difflib
import re
from dataclasses import dataclass
from pathlib import Path

# A gloss may follow the term after " — " or ": "; the term is the head of the line.
_GLOSS = re.compile(r"\s+[—–-]\s+|:\s+")
# A word as the model wrote it: leading punctuation, the bare word, trailing punctuation.
_SPLIT = re.compile(r"^(\W*)(.*?)(\W*)$")
_SENTENCE_END = (".", "!", "?")
# How alike a heard word and a known term must be before the term wins. Loosen it and
# ordinary speech starts getting rewritten; tighten it and a real miss goes uncaught
# ("hideas" reads as 0.86 of the way to "Highdeas").
_THRESHOLD = 0.82
# Under this many letters, "sounds like" says nothing at all — "note" is 0.86 of the way
# to the name "Noe" — so a short term is only ever matched by its own spelling.
_GUESSABLE = 5


def read_lexicon(path):
    """The terms in a lexicon file: the head of each line, with any gloss, bullet,
    blank line, or `#` comment stripped off. No file, no terms — without a lexicon a
    transcript reads exactly as it did before there was one."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return ()
    terms = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line[0] in "-*•":
            line = line[1:].strip()
        term = _GLOSS.split(line, maxsplit=1)[0].strip()
        if term:
            terms.append(term)
    return tuple(terms)


def corrections(tokens, terms, *, threshold=_THRESHOLD):
    """Where `tokens` missed a known term, as `(index, length, replacement)`.

    A term is one word or several, and the model may have written it as some other
    number of words — a compound name comes back as its halves ("notes nook") — so
    runs of words are read too, and a matched run collapses into the one term."""
    if not terms:
        return ()
    lexicon = _Lexicon.of(terms)
    split = [_SPLIT.match(token).groups() for token in tokens]
    found, index = [], 0
    while index < len(split):
        match = _match_at(split, index, lexicon, threshold)
        if match is None:
            index += 1
            continue
        size, term = match
        found.append((index, size, f"{split[index][0]}{term}{split[index + size - 1][2]}"))
        index += size
    return tuple(found)


def _match_at(split, start, lexicon, threshold):
    """The `(length, term)` of the longest run of words at `start` that missed a known
    term, or None. Longest first, so "Sagittal notation" wins over a stray one-word
    match inside it."""
    for size in range(min(lexicon.longest, len(split) - start), 0, -1):
        window = split[start:start + size]
        if any(token[2].endswith(_SENTENCE_END) for token in window[:-1]):
            continue  # a name is never spoken across a full stop
        heard = " ".join(word for _, word, _ in window if word)
        term = lexicon.match(heard, size, threshold) if heard else None
        if term is not None:
            return size, term
    return None


@dataclass(frozen=True)
class _Lexicon:
    """The known terms arranged for matching: by how many words each is written as,
    and by the letters each spells."""
    by_words: dict
    spelled: dict
    longest: int

    @classmethod
    def of(cls, terms):
        by_words, spelled = {}, {}
        for term in terms:
            spelled[_letters(term)] = term
            if len(_letters(term)) >= _GUESSABLE:
                by_words.setdefault(len(term.split()), []).append(term)
        # A term of N words may have been heard as one word more than that: the model
        # splits a name it doesn't know, it doesn't invent extra ones.
        return cls(by_words, spelled, max(by_words, default=1) + 1)

    def match(self, heard, words, threshold):
        """The term this run of `words` words missed, or None.

        A run of the term's own word count is matched by ear — it may be spelled any
        number of ways wrong. A longer run has to spell the term outright, letter for
        letter, or ordinary speech starts getting rewritten: heard as words, "fun
        times" is a near-perfect match for FunTime, and "a sauna" for Asana.

        One word that already spells the term is left as it is. Half the names worth
        knowing are ordinary words too ("Apple", "Willow", "Maps"), and a memo full of
        capitalised nouns is a worse read than one that never guessed."""
        if words > 1 and _letters(heard) in self.spelled:
            return self.spelled[_letters(heard)]
        return _closest(heard, self.by_words.get(words, ()), threshold)


def _letters(text):
    """`text` as bare letters and digits — how a term reads once the model's spacing,
    case, and punctuation are set aside."""
    return "".join(c for c in text.lower() if c.isalnum())


def _closest(heard, terms, threshold):
    """The known term closest to what was `heard` (case-insensitively), or None if none
    is close.

    A term that simply contains what was heard — "xenharmonic" around "harmonic" — is
    no match at all, however alike the two read: the model wrote a whole word of its
    own, and a whole word is a word that was said. It holds the other way round too,
    where the term is already spelled correctly inside a longer word."""
    lowered, bare = heard.lower(), _letters(heard)
    best, best_score = None, 0.0
    for term in terms:
        if bare in _letters(term) or _letters(term) in bare:
            continue
        score = difflib.SequenceMatcher(None, lowered, term.lower()).ratio()
        if score > best_score:
            best, best_score = term, score
    return best if best_score >= threshold else None
