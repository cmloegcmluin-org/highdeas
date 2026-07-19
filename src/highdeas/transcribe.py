"""Transcribe voice-memo audio locally with NVIDIA Parakeet (via onnx-asr)."""
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from highdeas.audio import NO_WINDOW as _NO_WINDOW
from highdeas.audio import locate_ffmpeg as _default_ffmpeg
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


@dataclass(frozen=True)
class TimedWord:
    """A spoken word and the second, into the recording, that it starts on."""
    start: float
    text: str


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
    return onnx_asr.load_model(name, providers=["CPUExecutionProvider"]).with_timestamps()


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
    """`tokens` as the `(index, length, replacement)` of `fixes` leave them: each token
    paired with the index it came from, and each corrected run standing as the one term
    it missed, at the index the run began on — which is to say at the moment it began."""
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


def _corrected(spoken, terms):
    """`spoken` as it would read had the model known these terms: every near-miss of
    one swapped for the term it missed, in the text and in the word timings alike.

    The text and the timed words are two tellings of the same speech and need not agree
    word for word, so each is read against the lexicon on its own terms."""
    tokens = spoken.text.split()
    fixes = corrections(tokens, terms)
    if not fixes:
        return spoken  # nothing in the lexicon was misheard — hand back what came
    heard = [word.text for word in spoken.words]
    return Transcript(
        _respaced(spoken.text, _applied(tokens, fixes)),
        tuple(TimedWord(spoken.words[index].start, token) for index, token
              in _applied(heard, corrections(heard, terms))),
    )


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

    def transcribe(self, audio_path):
        wav = self._decode(audio_path)
        recognized = self._get_model().recognize(wav)
        # The model rarely returns nothing; it renders humming as filler and noise as a
        # confident hallucination. Relabel those as [singing]/[unclear] before storing.
        # A relabelled note drops its word timings — there are no real words to light up.
        marked = mark_nonspeech(recognized.text)
        if marked == recognized.text:
            return _corrected(Transcript(recognized.text,
                                         _to_words(recognized.tokens, recognized.timestamps)),
                              self._read_terms())
        return Transcript(marked)
