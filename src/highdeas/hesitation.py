"""Leave out the sounds he made while he was thinking.

He says "um" and "uh" while he finds the next word, and the model — a speech
recognizer, doing its job — writes both down. Nothing about them is worth keeping: a
memo is read back for what it says, and two thirds of the notes he has recorded carry
at least one.

They are dropped here, before anything else reads the transcript. Two things follow
from dropping a word rather than relabelling one. A sound that opened a sentence was
carrying that sentence's capital, so the word left standing takes it; and a memo that
was nothing but hesitation comes out empty, which is a state the relabelling after this
already knows how to show.

Only these two sounds. The wordless ones — "mm", "hmm", a hummed tune — belong to
nonspeech, which reads them as singing and has its own reasons for what it leaves; and
the filler that is made of real words ("like", "you know") can't be cut without cutting
the sentences that use those words for their meaning."""
import re

# "um" and "uh", however long he held the sound: the model spells a held sound out at
# the length it was held, which is why the hums nonspeech reads are matched by shape
# too. No English word is spelled from a u followed only by m and h.
_HESITATION = re.compile(r"u[mh]+", re.IGNORECASE)
_SENTENCE_END = (".", "!", "?")


def without_hesitations(tokens):
    """`tokens` with every hesitation dropped, each survivor paired with the index it
    came from. A survivor that inherits the start of a sentence inherits its capital."""
    kept, opening = [], False
    for index, token in enumerate(tokens):
        if _is_hesitation(token):
            opening = opening or _opens_a_sentence(tokens, index)
            continue
        kept.append((index, _capitalized(token) if opening else token))
        opening = False
    return tuple(kept)


def _opens_a_sentence(tokens, index):
    """Whether the token at `index` is the first word of a sentence.

    A token with no letters in it — the "-" a dictated list is laid out with — is read
    straight past: it is punctuation the model set down, not a word said before the
    sound, so the sentence it opens is still the sound's to open."""
    while index and not any(c.isalpha() for c in tokens[index - 1]):
        index -= 1
    return index == 0 or tokens[index - 1].endswith(_SENTENCE_END)


def _is_hesitation(token):
    """Whether `token` is one of the sounds, however the model punctuated it. The
    punctuation is read past rather than kept: a comma around the sound was the pause
    being written down, and it has nothing left to sit beside once the sound is gone.

    A whole word of it, and nothing less — an *umbrella* he actually said is a worse
    thing to lose than an "um" is to keep."""
    return _HESITATION.fullmatch("".join(c for c in token if c.isalpha())) is not None


def _capitalized(token):
    """`token` with its first letter made a capital and the rest left alone — never
    `str.capitalize`, which would take the rest of an "OK" or a "PDF" back down."""
    return token[:1].upper() + token[1:]
