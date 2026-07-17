"""The transcriber can't read a sung note — the ASR model hears melody as nothing.
These pin how we tell singing (sustained, steady pitch) apart from speech too
unclear to make out (noise, silence, broken voicing), so a failed transcription
shows `[singing]` rather than `[unclear]`."""
import wave

import numpy as np

from highdeas.singing import is_singing, looks_like_singing

RATE = 16000


def tone(freq, secs, rate=RATE):
    t = np.arange(int(secs * rate)) / rate
    return np.sin(2 * np.pi * freq * t)


def test_sustained_note_reads_as_singing():
    assert looks_like_singing(tone(220, 1.5), RATE) is True


def test_a_melody_of_held_notes_reads_as_singing():
    notes = np.concatenate([tone(f, 0.4) for f in (220, 262, 294, 330)])
    assert looks_like_singing(notes, RATE) is True


def test_white_noise_is_not_singing():
    rng = np.random.default_rng(0)
    assert looks_like_singing(rng.standard_normal(int(1.5 * RATE)), RATE) is False


def test_silence_is_not_singing():
    assert looks_like_singing(np.zeros(int(1.5 * RATE)), RATE) is False


def test_broken_voicing_over_consonant_noise_is_not_singing():
    # Short pitched blips separated by aperiodic bursts — the shape of speech, where
    # too little of the recording is a steady held pitch to call it a song.
    rng = np.random.default_rng(1)
    parts = []
    for i in range(8):
        parts.append(tone(150 + i * 7, 0.06))
        parts.append(0.4 * rng.standard_normal(int(0.09 * RATE)))
    assert looks_like_singing(np.concatenate(parts), RATE) is False


def test_a_clip_too_short_to_judge_is_not_singing():
    assert looks_like_singing(tone(220, 0.1), RATE) is False


def test_is_singing_reads_a_hummed_wav_off_disk(tmp_path):
    path = tmp_path / "hum.wav"
    _write_wav(path, tone(220, 1.5))
    assert is_singing(path) is True


def test_is_singing_hears_noise_off_disk_as_not_singing(tmp_path):
    rng = np.random.default_rng(2)
    path = tmp_path / "noise.wav"
    _write_wav(path, rng.standard_normal(int(1.5 * RATE)))
    assert is_singing(path) is False


def _write_wav(path, samples, rate=RATE):
    pcm = (np.clip(samples / np.max(np.abs(samples)), -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm.tobytes())
