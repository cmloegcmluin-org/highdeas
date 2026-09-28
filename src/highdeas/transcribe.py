"""Transcribe voice-memo audio locally with NVIDIA Parakeet (via onnx-asr)."""
import re
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy

from highdeas.audio import NO_WINDOW as _NO_WINDOW
from highdeas.audio import locate_ffmpeg as _default_ffmpeg
from highdeas.hesitation import without_hesitations
from highdeas.nonspeech import mark_nonspeech
from highdeas.vocabulary import corrections


class AudioDecodeError(Exception):
    """Raised when ffmpeg fails to decode an audio file."""


def decode_to_wav(src, *, out_dir=None, ffmpeg_exe=None, runner=subprocess.run,
                  locate_ffmpeg=_default_ffmpeg):
    if ffmpeg_exe is None:
        ffmpeg_exe = locate_ffmpeg()
    src = Path(src)
    out_dir = Path(out_dir) if out_dir is not None else Path(tempfile.gettempdir())
    out = out_dir / (src.stem + ".wav")
    cmd = [ffmpeg_exe, "-y", "-i", str(src), "-ar", "16000", "-ac", "1", str(out)]
    result = runner(cmd, capture_output=True, text=True, creationflags=_NO_WINDOW)
    if result.returncode != 0:
        raise AudioDecodeError(f"ffmpeg failed to decode {src.name}: {result.stderr}")
    return out


DEFAULT_MODEL = "nemo-parakeet-tdt-0.6b-v3"

# How much of a recording the model will take in one go. Its exported encoder carries
# a positional table 5000 frames wide — 400 seconds at the encoder's 80ms stride — and
# anything longer fails outright ("Attempting to broadcast an axis by a dimension other
# than 1"), on every scan, forever. So a longer recording is heard in pieces this size,
# which leaves room to spare under that ceiling.
HEARABLE_SECONDS = 360.0
# How far back from that ceiling to hunt for the quietest moment to end a piece on, and
# how long a stretch is judged for quiet. A seam that falls in a pause costs the
# transcript nothing; one through the middle of a word costs it that word twice, garbled
# at the end of one piece and again at the start of the next.
_PAUSE_HUNT_SECONDS = 45.0
_PAUSE_SECONDS = 0.25
# The model goes wrong on a knife edge nothing in the audio explains. Across a long
# silence inside a recording it has written words that were never said, all on the
# instant speech resumed, and then read none of the speech that followed; and handed a
# stretch of loud, clear speech it has returned nothing at all, or every word of it,
# depending on a quarter-second's difference in where the stretch began. Nothing marks
# either from the inside, but both leave sound with no words on it. So the words are held
# against the sound: where a gap of LONG_PAUSE_SECONDS between two words it did hear says
# a long pause, the recording is heard again in the stretches of speech between its long
# pauses, and any stretch that still leaves loud sound with no word on it is heard again
# from a different start until its words cover the sound. The re-heard reading replaces
# the first only when it covers more of the recording's sound, so a recording the first
# reading already covered is left as it was.
LONG_PAUSE_SECONDS = 3.0
_PAUSE_MARGIN_SECONDS = 1.5
_WORD_SECONDS = 0.5
# Sound is a moment at _SOUND_LEVEL of the recording's own speech level (the median
# loudness where its words start) or louder; a word reaches from _WORD_LAG_SECONDS before
# it starts to _WORD_REACH_SECONDS after; and an uncovered run this long is worth hearing
# again. _SOUND_FLOOR is what a recording with no words at all is held against, as a
# fraction of full scale: room tone on his phone peaks near 0.01, his softest speech near
# 0.03.
_SOUND_LEVEL = 0.5
_SOUND_SECONDS = 1.5
_WORD_LAG_SECONDS = 0.6
_WORD_REACH_SECONDS = 1.5
_SOUND_FLOOR = 0.03
# Where each new hearing of a stretch begins, relative to the stretch, and how much
# silence is put in front of it: the model's answer changes with either.
_REHEAR_STARTS = ((0.0, 0.0), (-0.5, 0.0), (0.0, 0.5), (0.25, 0.0), (-1.0, 0.0), (0.0, 1.0))
# Past this many stretches the recording is not speech with a few pauses in it but
# something the model read only in scattered scraps -- music, noise -- which has no
# dropped speech to recover and is relabelled downstream. Cutting it up only burns the
# model, so it is left as the first reading heard it.
_MOST_STRETCHES = 8


@dataclass(frozen=True)
class TimedWord:
    """A spoken word and the second, into the recording, that it starts on."""
    start: float
    text: str


@dataclass(frozen=True)
class Recognition:
    """What the model made of a recording: the text, the sub-word tokens it decoded,
    and the second each was spoken at. The shape onnx-asr hands back, so a recording
    heard in pieces reads exactly like one heard in a single go."""
    text: str
    tokens: tuple = ()
    timestamps: tuple = ()


def _read_wav(path):
    """A decoded recording as float32 in [-1, 1], with its sample rate -- what onnx-asr
    would read off the file itself, read here so a long one can be handed over a piece
    at a time. `decode_to_wav` is the only writer of these, and it writes 16-bit mono."""
    with wave.open(str(path), "rb") as recording:
        rate = recording.getframerate()
        frames = recording.readframes(recording.getnframes())
    return numpy.frombuffer(frames, dtype="<i2").astype(numpy.float32) / 32768.0, rate


def _peaks(samples, rate):
    """How loud each `_PAUSE_SECONDS` of the recording gets, first to last."""
    width = int(_PAUSE_SECONDS * rate)
    whole = len(samples) - len(samples) % width
    return numpy.abs(samples[:whole]).reshape(-1, width).max(axis=1)


def _quietest(samples, first, last, width):
    """The middle of the quietest `width`-long stretch of `samples[first:last]`."""
    at = min(range(first, last - width + 1, width),
             key=lambda start: numpy.abs(samples[start:start + width]).max())
    return at + width // 2


def _hearable(samples, rate, start, end):
    """`samples[start:end]` in stretches the model can take, as (start, end) sample
    offsets, each running as near the ceiling as it can while still ending on a pause,
    so every stretch is hearable and no seam falls through the middle of a word."""
    span, hunt, pause = (int(seconds * rate) for seconds in
                         (HEARABLE_SECONDS, _PAUSE_HUNT_SECONDS, _PAUSE_SECONDS))
    edges = [start]
    while end - edges[-1] > span:
        edges.append(_quietest(samples, edges[-1] + span - hunt, edges[-1] + span, pause))
    edges.append(end)
    return list(zip(edges, edges[1:]))


def _between_long_pauses(samples, rate, starts):
    """The recording in stretches of speech, as (start, end) sample offsets, cut apart
    wherever `starts` -- the seconds the words heard so far began on -- leave a gap of
    `LONG_PAUSE_SECONDS` or more. Nothing when they leave no such gap.

    Each stretch keeps no more than a margin of the quiet either side of its words, cut
    at the quietest moment inside that margin, past the word the stretch ends on."""
    margin, word, pause = (int(seconds * rate) for seconds in
                           (_PAUSE_MARGIN_SECONDS, _WORD_SECONDS, _PAUSE_SECONDS))
    stretches, at = [], 0
    for before, after in zip(starts, starts[1:]):
        if after - before < LONG_PAUSE_SECONDS:
            continue
        before, after = int(before * rate), int(after * rate)
        middle = (before + after) // 2
        stretches.append((at, _quietest(samples, before + word, min(before + margin, middle), pause)))
        at = _quietest(samples, max(after - margin, middle), after, pause)
    if stretches:
        stretches.append((at, len(samples)))
    return stretches


def _sound_level(peaks, starts):
    """How loud the recording is where its words start -- the level its speech is at --
    or the floor, when it has no words to measure."""
    if not starts:
        return _SOUND_FLOOR
    at = [peaks[min(int(start / _PAUSE_SECONDS), len(peaks) - 1)] for start in starts]
    return max(_SOUND_LEVEL * float(numpy.median(at)), _SOUND_FLOOR)


def _unheard(peaks, starts, level, first=0.0, last=None):
    """The stretches of sound between `first` and `last` seconds that no word reaches,
    as (begin, end) seconds: sound is a moment at `level` or louder, and a word reaches
    from `_WORD_LAG_SECONDS` before it starts to `_WORD_REACH_SECONDS` after."""
    starts = numpy.asarray(sorted(starts), dtype=float)
    last = len(peaks) * _PAUSE_SECONDS if last is None else last
    stretches, since = [], None
    for index in range(int(first / _PAUSE_SECONDS), int(numpy.ceil(last / _PAUSE_SECONDS)) + 1):
        moment = index * _PAUSE_SECONDS
        sound = index < len(peaks) and moment < last and peaks[index] >= level
        reached = (numpy.searchsorted(starts, moment - _WORD_REACH_SECONDS)
                   < numpy.searchsorted(starts, moment + _WORD_LAG_SECONDS, side="right"))
        if sound and not reached:
            since = moment if since is None else since
        elif since is not None:
            stretches.append((since, moment))
            since = None
    return stretches


def _uncovered(peaks, said, level, first, last):
    """The seconds of sound between `first` and `last` that `said`'s words leave with no
    word on them -- how much of a stretch's speech a hearing failed to reach."""
    starts = [word.start for word in _to_words(said.tokens, said.timestamps)]
    return sum(end - begin for begin, end in _unheard(peaks, starts, level, first, last))


def _joined(parts):
    """Several stretch hearings put back together as one, in the order they were heard.
    Each already carries its timings in the recording's own seconds, so the words stay
    where they were spoken."""
    return Recognition(
        text=" ".join(part.text for part in parts if part.text),
        tokens=tuple(token for part in parts for token in part.tokens),
        timestamps=tuple(stamp for part in parts for stamp in part.timestamps),
    )


class HearsAnyLength:
    """The ASR model, able to take a recording of any length, and held to hearing all of
    it.

    Past `HEARABLE_SECONDS` the model refuses a recording rather than shortening its
    answer, so a long one is heard in pieces and the pieces put back together -- each
    piece's word timings slid to where in the recording that piece starts. And the model
    goes wrong across a long pause and on a knife-edge start offset, either way leaving
    sound with no words on it, so its words are held against the sound: a recording whose
    first reading leaves loud sound uncovered is heard again in the stretches between its
    long pauses, each stretch re-heard from a different start until its words cover the
    sound, and the re-reading kept only when it covers more of the recording than the
    first (see LONG_PAUSE_SECONDS, _REHEAR_STARTS).

    Hearing one in pieces is also the only honest place to count how far along it is,
    which is what `progress` is called with after each: the fraction of the recording
    read so far, so the page has a real number to show rather than a guess at the clock.
    A recording that fits says so once, when it is read, and each stretch re-heard says
    the whole of it has been read.

    It is the only word the caller gets in mid-read, so it is also how a read is called
    off: raise out of `progress` and the rest of the recording goes unread. That is what
    throwing a recording away from its row does (service.Abandoned) -- the minutes a long
    one costs are the reason it can be thrown away before it is read at all."""

    def __init__(self, model):
        self._model = model

    def recognize(self, wav, progress=None):
        samples, rate = _read_wav(wav)
        heard = self._hear(samples, rate, _hearable(samples, rate, 0, len(samples)), progress)
        peaks, span = _peaks(samples, rate), len(samples) / rate
        starts = [word.start for word in _to_words(heard.tokens, heard.timestamps)]
        level = _sound_level(peaks, starts)
        if _uncovered(peaks, heard, level, 0.0, span) < _SOUND_SECONDS:
            return heard  # the words already cover the sound
        stretches = _between_long_pauses(samples, rate, starts)
        if not stretches or len(stretches) > _MOST_STRETCHES:
            return heard
        report = None if progress is None else (lambda _: progress(1.0))
        stitched = _joined([self._cover(samples, rate, peaks, level, start, end, report)
                            for start, end in stretches])
        if _uncovered(peaks, stitched, level, 0.0, span) < _uncovered(peaks, heard, level, 0.0, span):
            return stitched
        return heard

    def _cover(self, samples, rate, peaks, level, start, end, progress):
        """The stretch `samples[start:end]`, heard from the starting points of
        `_REHEAR_STARTS` and kept at the one whose words cover the most of its sound."""
        best = self._hear(samples, rate, _hearable(samples, rate, start, end), None)
        gap = _uncovered(peaks, best, level, start / rate, end / rate)
        for shift, silence in _REHEAR_STARTS[1:]:
            if gap <= 0:
                break
            first = max(0, round(start + shift * rate))
            if (end - first) / rate > HEARABLE_SECONDS and silence:
                continue
            piece = numpy.concatenate([numpy.zeros(round(silence * rate), dtype=numpy.float32),
                                       samples[first:end]])
            said = self._hear(piece, rate, _hearable(piece, rate, 0, len(piece)), None,
                              at=first / rate - silence)
            reached = _uncovered(peaks, said, level, start / rate, end / rate)
            if reached < gap:
                best, gap = said, reached
        if progress is not None:
            progress(1.0)
        return best

    def _hear(self, samples, rate, stretches, progress, at=0.0):
        heard = []
        for start, end in stretches:
            heard.append((at + start / rate, self._model.recognize(samples[start:end], sample_rate=rate)))
            if progress is not None:
                progress(end / len(samples))
        return Recognition(
            text=" ".join(said.text for _, said in heard if said.text),
            tokens=tuple(token for _, said in heard for token in said.tokens or ()),
            timestamps=tuple(round(begins + stamp, 3) for begins, said in heard
                             for stamp in said.timestamps or ()),
        )


@dataclass(frozen=True)
class Transcript:
    """What a recording said, and when it said each word."""
    text: str
    words: tuple = ()


def _load_parakeet(name):
    import onnx_asr

    # The timestamped adapter reports the sub-word tokens and their emission times
    # alongside the text, which is what lets the editor light up each word as the
    # recording plays. Transcription is CPU-by-design on every platform: left to
    # choose, onnxruntime picks CoreML on macOS, which fails to initialize this
    # external-data model ("model_path must not be empty").
    return HearsAnyLength(
        onnx_asr.load_model(name, providers=["CPUExecutionProvider"]).with_timestamps())


def _to_words(tokens, timestamps):
    """Gather the model's sub-word tokens into whole words with a start time.

    The model emits tokens like " d", "ust", "ing", ".", each stamped with the
    second it was spoken. A leading space starts a new word; everything else
    continues the word before it — including trailing punctuation, which belongs
    to the word it follows."""
    words = []
    for token, start in zip(tokens or (), timestamps or ()):
        if words and not token[:1].isspace():
            words[-1] = TimedWord(words[-1].start, words[-1].text + token)
        else:
            words.append(TimedWord(start, token.strip()))
    return tuple(word for word in words if word.text)


def _applied(tokens, fixes):
    """`tokens` as the `(index, length, replacement)` of `fixes` leave them, in the
    kept form `_rewritten` reads: each token paired with the index it came from, and
    each corrected run standing as the one term it missed, at the index the run began
    on — which is to say at the moment it began."""
    out, index = [], 0
    for at, size, replacement in fixes:
        out.extend((n, tokens[n]) for n in range(index, at))
        out.append((at, replacement))
        index = at + size
    out.extend((n, tokens[n]) for n in range(index, len(tokens)))
    return tuple(out)


def _respaced(text, kept):
    """`text` with only `kept` left of it: each survivor spelled as `kept` spells it,
    in the place it was, spaced from its neighbours exactly as it was.

    The spacing has to be carried rather than rebuilt. He dictates lists, and the model
    lays one out a line per item — join the surviving words with single spaces and his
    list comes back as a paragraph."""
    if not kept:
        return ""
    spans = [word.span() for word in re.finditer(r"\S+", text)]
    out = [text[:spans[0][0]]]
    for place, (index, token) in enumerate(kept):
        if place:
            out.append(text[spans[index - 1][1]:spans[index][0]])
        out.append(token)
    out.append(text[spans[-1][1]:])
    return "".join(out)


def _rewritten(spoken, edit):
    """`spoken` as `edit` rewrites it, in the text and in the word timings alike.

    `edit` reads a list of words and answers with the ones worth keeping, each paired
    with the index it came from. A kept word takes the timing of the index it answers
    with, so a run gathered into one term lights up from the moment the run began.

    The text and the timed words are two tellings of the same speech and need not agree
    word for word, so each is edited against itself rather than one being read off the
    other."""
    tokens = spoken.text.split()
    kept = edit(tokens)
    if kept == tuple(enumerate(tokens)):
        return spoken  # nothing to rewrite — hand back what came, spacing and all
    return Transcript(
        _respaced(spoken.text, kept),
        tuple(TimedWord(spoken.words[index].start, token) for index, token
              in edit([word.text for word in spoken.words])),
    )


def _corrected(spoken, terms):
    """`spoken` as it would read had the model known these terms: every near-miss of
    one swapped for the term it missed."""
    return _rewritten(spoken, lambda words: _applied(words, corrections(words, terms)))


class Transcriber:
    def __init__(self, *, model=None, decode=decode_to_wav,
                 model_loader=_load_parakeet, model_name=DEFAULT_MODEL,
                 read_terms=lambda: ()):
        self._model = model
        self._decode = decode
        self._model_loader = model_loader
        self._model_name = model_name
        self._read_terms = read_terms

    def _get_model(self):
        if self._model is None:
            self._model = self._model_loader(self._model_name)
        return self._model

    def transcribe(self, audio_path, progress=None):
        wav = self._decode(audio_path)
        recognized = self._get_model().recognize(wav, progress=progress)
        # He says "um" and "uh" while he thinks and the model writes both down. They go
        # first, so that a note that was nothing else is left empty for the next step
        # to read as [unclear].
        heard = Transcript(recognized.text,
                           _to_words(recognized.tokens, recognized.timestamps))
        spoken = _rewritten(heard, without_hesitations)
        # The model rarely returns nothing; it renders humming as filler and noise as a
        # confident hallucination. Relabel those as [singing]/[unclear] before storing.
        # A relabelled note drops its word timings — there are no real words to light up.
        marked = mark_nonspeech(spoken.text)
        if marked == spoken.text:
            return _corrected(spoken, self._read_terms())
        return Transcript(marked)
