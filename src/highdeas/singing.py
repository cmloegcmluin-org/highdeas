"""Tell singing apart from speech too unclear to make out.

The ASR model is a speech recognizer: it hears a sung note as nothing and hands
back an empty transcript. But so does a mumble, a bad recording, or a room of
noise. When the transcriber gets nothing, it asks here which it was, so the note
reads `[singing]` rather than `[unclear]` instead of showing blank.

The tell is sustained, steady pitch. A held sung note keeps one pitch across many
analysis frames; speech slides and jumps between pitches and is broken up by
unvoiced consonants, and noise has no pitch at all. So the question is how much of
the recording is voiced at a pitch that holds still from one frame to the next."""
import wave
from pathlib import Path

import numpy as np

_WINDOW_S = 0.025      # 25 ms analysis window
_HOP_S = 0.010         # 10 ms between windows
_PITCH_MAX_HZ = 1000   # top of the sung range we look for
_PITCH_MIN_HZ = 80     # bottom of it
_ACTIVE_RMS = 0.05     # a frame quieter than this (peak-normalized) is silence, not sound
_VOICED_NAC = 0.7      # normalized autocorrelation a frame needs to count as pitched
_SAME_NOTE = 1.06      # two pitches within ~6% (under a semitone) are the same held note
_MIN_VOICED = 20       # fewer pitched frames than this (~200 ms) is too little to judge
_VOICED_RATIO = 0.6    # this much of the sounding recording must be pitched
_STABILITY = 0.85      # and this much of that pitch must hold still, note to note
_MAX_SECONDS = 20      # judge on the opening; enough to decide, and bounds the cost


def is_singing(wav_path):
    """Whether the recording at `wav_path` (mono PCM WAV, as decode_to_wav writes) is
    a sung note the speech model couldn't read."""
    samples, rate = _read(wav_path)
    return looks_like_singing(samples, rate)


def looks_like_singing(samples, rate):
    """Whether `samples` are mostly a steady held pitch — the shape of singing."""
    lags, active = _voiced_lags(samples, rate)
    if len(lags) < _MIN_VOICED or len(lags) < _VOICED_RATIO * active:
        return False
    return _held_fraction(lags) >= _STABILITY


def _voiced_lags(samples, rate):
    """The pitch period of every voiced frame, and how many frames carried any sound.

    Pitch is kept as its autocorrelation lag in samples, not Hz: only the ratio of
    one frame's pitch to the next matters downstream, and that ratio is the same
    either way, so the sample rate never has to enter the pitch itself."""
    frame_len, hop = int(_WINDOW_S * rate), int(_HOP_S * rate)
    lag_min, lag_max = max(1, int(rate / _PITCH_MAX_HZ)), int(rate / _PITCH_MIN_HZ)
    samples = np.asarray(samples, dtype=np.float64)
    peak = np.max(np.abs(samples)) if samples.size else 0.0
    if peak == 0:
        return [], 0
    samples = samples / peak
    lags, active = [], 0
    for start in range(0, len(samples) - frame_len + 1, hop):
        frame = samples[start:start + frame_len]
        if np.sqrt(np.mean(frame * frame)) < _ACTIVE_RMS:
            continue
        active += 1
        nac, lag = _frame_lag(frame, lag_min, lag_max)
        if nac >= _VOICED_NAC and lag:
            lags.append(lag)
    return lags, active


def _frame_lag(frame, lag_min, lag_max):
    """A frame's pitch period and how periodic it is (0–1), by normalized autocorrelation:
    the shifted-self correlation peaks at the period of a pitched frame and stays low for
    noise. Returns the peak's height and the lag it sits at."""
    x = frame - frame.mean()
    best_nac, best_lag = 0.0, 0
    for lag in range(lag_min, min(lag_max, len(x) - 1) + 1):
        a, b = x[:-lag], x[lag:]
        denom = np.sqrt(float(np.dot(a, a)) * float(np.dot(b, b)))
        if denom == 0:
            continue
        nac = float(np.dot(a, b)) / denom
        if nac > best_nac:
            best_nac, best_lag = nac, lag
    return best_nac, best_lag


def _held_fraction(lags):
    """The share of note-to-note steps that stay within a held note's width."""
    periods = np.asarray(lags, dtype=np.float64)
    steps = np.abs(np.log(periods[1:] / periods[:-1]))
    return float(np.mean(steps < np.log(_SAME_NOTE)))


def _read(path):
    """Read up to the opening `_MAX_SECONDS` of a WAV as a mono float array."""
    with wave.open(str(Path(path)), "rb") as wav:
        rate, channels, width = wav.getframerate(), wav.getnchannels(), wav.getsampwidth()
        raw = wav.readframes(min(wav.getnframes(), int(rate * _MAX_SECONDS)))
    dtype = {1: np.uint8, 2: np.int16, 4: np.int32}.get(width)
    if dtype is None:
        raise ValueError(f"unsupported WAV sample width: {width} bytes")
    data = np.frombuffer(raw, dtype=dtype).astype(np.float64)
    if width == 1:                       # 8-bit PCM is unsigned, centered on 128
        data = data - 128
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    return data, rate
