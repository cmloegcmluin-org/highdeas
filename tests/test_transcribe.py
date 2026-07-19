import subprocess

import pytest

from highdeas.transcribe import AudioDecodeError, Transcriber, decode_to_wav


class FakeRunner:
    def __init__(self, returncode=0, stderr=""):
        self.returncode = returncode
        self.stderr = stderr
        self.calls = []
        self.kwargs = []

    def __call__(self, cmd, **kwargs):
        self.calls.append(cmd)
        self.kwargs.append(kwargs)
        return subprocess.CompletedProcess(cmd, self.returncode, stdout="", stderr=self.stderr)


def test_decode_to_wav_builds_16k_mono_command_and_returns_wav_path(tmp_path):
    runner = FakeRunner()

    out = decode_to_wav(tmp_path / "voice.m4a", out_dir=tmp_path, ffmpeg_exe="ff", runner=runner)

    assert out == tmp_path / "voice.wav"
    assert runner.calls[0] == [
        "ff", "-y", "-i", str(tmp_path / "voice.m4a"),
        "-ar", "16000", "-ac", "1", str(tmp_path / "voice.wav"),
    ]


def test_decode_to_wav_locates_ffmpeg_when_not_given(tmp_path):
    runner = FakeRunner()

    decode_to_wav(tmp_path / "voice.m4a", out_dir=tmp_path, runner=runner,
                  locate_ffmpeg=lambda: "LOCATED_FFMPEG")

    assert runner.calls[0][0] == "LOCATED_FFMPEG"


def test_decode_to_wav_raises_on_ffmpeg_failure(tmp_path):
    runner = FakeRunner(returncode=1, stderr="Invalid data found when processing input")

    with pytest.raises(AudioDecodeError, match="Invalid data found"):
        decode_to_wav(tmp_path / "bad.m4a", out_dir=tmp_path, ffmpeg_exe="ff", runner=runner)


def test_decode_to_wav_hides_console_window(tmp_path):
    """ffmpeg must run without flashing a console window (CREATE_NO_WINDOW on Windows)."""
    runner = FakeRunner()

    decode_to_wav(tmp_path / "voice.m4a", out_dir=tmp_path, ffmpeg_exe="ff", runner=runner)

    assert runner.kwargs[0].get("creationflags") == getattr(subprocess, "CREATE_NO_WINDOW", 0)


class Recognition:
    """What onnx-asr's timestamped adapter hands back: the text, plus the sub-word
    tokens it decoded and the second each was emitted at."""

    def __init__(self, text, tokens=(), timestamps=()):
        self.text = text
        self.tokens = tokens
        self.timestamps = timestamps


class FakeModel:
    def __init__(self, result):
        self.result = result
        self.recognized = []

    def recognize(self, wav):
        self.recognized.append(wav)
        return self.result


def test_transcriber_decodes_then_recognizes(tmp_path):
    model = FakeModel(Recognition("hello world"))
    decoded = tmp_path / "voice.wav"
    decoded_calls = []

    def fake_decode(src):
        decoded_calls.append(src)
        return decoded

    spoken = Transcriber(model=model, decode=fake_decode).transcribe(tmp_path / "voice.m4a")

    assert spoken.text == "hello world"
    assert decoded_calls == [tmp_path / "voice.m4a"]
    assert model.recognized == [decoded]


def test_transcriber_lazy_loads_model_once(tmp_path):
    model = FakeModel(Recognition("hi"))
    load_calls = []

    def fake_loader(name):
        load_calls.append(name)
        return model

    transcriber = Transcriber(
        model_loader=fake_loader,
        model_name="the-model",
        decode=lambda src: tmp_path / "x.wav",
    )
    assert load_calls == []  # nothing loaded until first use

    transcriber.transcribe(tmp_path / "a.m4a")
    transcriber.transcribe(tmp_path / "b.m4a")

    assert load_calls == ["the-model"]  # loaded exactly once, by name


def test_transcriber_groups_sub_word_tokens_into_words_it_can_time(tmp_path):
    # The model emits sub-word tokens, each stamped with the second it was spoken:
    # a leading space starts a new word, everything else continues the one before.
    # The editor highlights whole words, so gather them here rather than there.
    model = FakeModel(Recognition(
        "I need a dusting.",
        tokens=[" I", " need", " a", " d", "ust", "ing", "."],
        timestamps=[0.96, 1.52, 2.08, 2.32, 2.48, 2.72, 2.88],
    ))

    spoken = Transcriber(model=model, decode=lambda src: tmp_path / "x.wav").transcribe(tmp_path / "a.m4a")

    assert [(w.start, w.text) for w in spoken.words] == [
        (0.96, "I"), (1.52, "need"), (2.08, "a"), (2.32, "dusting."),
    ]


def test_transcriber_reports_no_words_when_the_model_gives_no_timings(tmp_path):
    # A model without timestamp support still transcribes; the note just can't
    # highlight along with its audio.
    model = FakeModel(Recognition("hello world", tokens=None, timestamps=None))

    spoken = Transcriber(model=model, decode=lambda src: tmp_path / "x.wav").transcribe(tmp_path / "a.m4a")

    assert spoken.text == "hello world"
    assert spoken.words == ()


def test_transcriber_relabels_an_empty_result_as_unclear(tmp_path):
    # The model heard no words: show a placeholder, never a blank note the user has to
    # guess the emptiness of.
    model = FakeModel(Recognition(""))

    spoken = Transcriber(model=model, decode=lambda src: tmp_path / "x.wav").transcribe(
        tmp_path / "a.m4a")

    assert spoken.text == "[unclear]"
    assert spoken.words == ()


def test_transcriber_relabels_humming_as_singing_and_drops_its_timings(tmp_path):
    # Humming comes back as filler tokens with timings; the note reads [singing] and
    # keeps none of them — there are no real words to light up as it plays.
    model = FakeModel(Recognition("Mm-hmm.", tokens=[" Mm", "-hmm", "."],
                                  timestamps=[0.2, 0.5, 0.9]))

    spoken = Transcriber(model=model, decode=lambda src: tmp_path / "x.wav").transcribe(
        tmp_path / "a.m4a")

    assert spoken.text == "[singing]"
    assert spoken.words == ()


def test_transcriber_keeps_real_speech_and_its_word_timings(tmp_path):
    model = FakeModel(Recognition("I need a dusting.", tokens=[" I", " need", " a",
                                  " dusting", "."], timestamps=[0.1, 0.3, 0.6, 0.8, 1.1]))

    spoken = Transcriber(model=model, decode=lambda src: tmp_path / "x.wav").transcribe(
        tmp_path / "a.m4a")

    assert spoken.text == "I need a dusting."
    assert [w.text for w in spoken.words] == ["I", "need", "a", "dusting."]


def test_transcriber_leaves_out_the_sounds_he_made_while_thinking(tmp_path):
    # "Um" and "uh" are speech, so nothing relabels them — they simply aren't worth
    # writing down. The word timings lose them with the text, or the editor would
    # light up a word the note no longer has.
    model = FakeModel(Recognition("Um okay, another thing.",
                                  tokens=[" Um", " okay", ",", " another", " thing", "."],
                                  timestamps=[0.1, 0.5, 0.7, 0.9, 1.3, 1.6]))

    spoken = Transcriber(model=model, decode=lambda src: tmp_path / "x.wav").transcribe(
        tmp_path / "a.m4a")

    assert spoken.text == "Okay, another thing."
    assert [(w.start, w.text) for w in spoken.words] == [
        (0.5, "Okay,"), (0.9, "another"), (1.3, "thing."),
    ]


def test_transcriber_reads_a_note_of_pure_hesitation_as_unclear(tmp_path):
    # Started, thought better of, stopped. The sounds go first and what is left is
    # nothing, which the relabelling below already knows how to show — so it has to
    # run after them, not before.
    model = FakeModel(Recognition("Um, uh.", tokens=[" Um", ",", " uh", "."],
                                  timestamps=[0.2, 0.4, 0.7, 0.9]))

    spoken = Transcriber(model=model, decode=lambda src: tmp_path / "x.wav").transcribe(
        tmp_path / "a.m4a")

    assert spoken.text == "[unclear]"
    assert spoken.words == ()


def test_transcriber_keeps_the_lines_of_a_grouped_note_it_takes_a_sound_out_of(tmp_path):
    # He dictates a list and the model lays it out a line per item. Rebuilding the
    # text from its words would run those lines into one paragraph.
    model = FakeModel(Recognition("- Um take out trash.\n- Nothing else.",
                                  tokens=[" -", " Um", " take", " out", " trash", ".",
                                          " -", " Nothing", " else", "."],
                                  timestamps=[0.1, 0.3, 0.5, 0.8, 1.0, 1.2,
                                              1.6, 1.8, 2.1, 2.3]))

    spoken = Transcriber(model=model, decode=lambda src: tmp_path / "x.wav").transcribe(
        tmp_path / "a.m4a")

    assert spoken.text == "- Take out trash.\n- Nothing else."


def test_transcriber_swaps_a_missed_term_for_the_word_he_actually_said(tmp_path):
    # The model has never heard of Highdeas and writes the nearest thing it knows.
    # His lexicon is what the transcript is read against before it is stored.
    model = FakeModel(Recognition("An idea for hideas.",
                                  tokens=[" An", " idea", " for", " hideas", "."],
                                  timestamps=[0.1, 0.3, 0.6, 0.8, 1.1]))

    spoken = Transcriber(model=model, decode=lambda src: tmp_path / "x.wav",
                         read_terms=lambda: ("Highdeas",)).transcribe(tmp_path / "a.m4a")

    assert spoken.text == "An idea for Highdeas."
    assert [w.text for w in spoken.words] == ["An", "idea", "for", "Highdeas."]


def test_transcriber_times_a_gathered_up_term_from_the_first_word_of_it(tmp_path):
    # A compound name comes back as its halves. The editor lights up whole words as
    # the recording plays, so the pair becomes the one word it was spoken as —
    # starting when the first half did, not when the second did.
    model = FakeModel(Recognition("Put it in notes nook.",
                                  tokens=[" Put", " it", " in", " notes", " nook", "."],
                                  timestamps=[0.1, 0.4, 0.7, 1.0, 1.4, 1.8]))

    spoken = Transcriber(model=model, decode=lambda src: tmp_path / "x.wav",
                         read_terms=lambda: ("Notesnook",)).transcribe(tmp_path / "a.m4a")

    assert spoken.text == "Put it in Notesnook."
    assert [(w.start, w.text) for w in spoken.words] == [
        (0.1, "Put"), (0.4, "it"), (0.7, "in"), (1.0, "Notesnook."),
    ]


def test_transcriber_keeps_the_lines_of_a_grouped_note_it_corrects_a_term_in(tmp_path):
    # Same list, corrected rather than trimmed: swapping a term in is no more licence
    # to reflow his lines than taking a sound out was.
    model = FakeModel(Recognition("- Call notes nook.\n- Nothing else.",
                                  tokens=[" -", " Call", " notes", " nook", ".",
                                          " -", " Nothing", " else", "."],
                                  timestamps=[0.1, 0.3, 0.6, 1.0, 1.2,
                                              1.6, 1.8, 2.1, 2.3]))

    spoken = Transcriber(model=model, decode=lambda src: tmp_path / "x.wav",
                         read_terms=lambda: ("Notesnook",)).transcribe(tmp_path / "a.m4a")

    assert spoken.text == "- Call Notesnook.\n- Nothing else."


def test_transcriber_asks_for_his_terms_afresh_for_every_recording(tmp_path):
    # He adds a term because he just watched a memo come out with it wrong, and
    # nobody restarts an app for that: the very next recording reads against the
    # list as it stands then.
    model = FakeModel(Recognition("hideas", tokens=[" hideas"], timestamps=[0.1]))
    lists = [(), ("Highdeas",)]
    transcriber = Transcriber(model=model, decode=lambda src: tmp_path / "x.wav",
                              read_terms=lambda: lists.pop(0))

    assert transcriber.transcribe(tmp_path / "a.m4a").text == "hideas"
    assert transcriber.transcribe(tmp_path / "b.m4a").text == "Highdeas"


def test_load_parakeet_pins_the_cpu_provider(monkeypatch):
    # Left to choose, onnxruntime picks CoreML on macOS, which fails to
    # initialize this external-data model ("model_path must not be empty").
    # Transcription is CPU-by-design on every platform, so say so.
    import sys
    from types import SimpleNamespace

    from highdeas.transcribe import _load_parakeet

    calls = []

    class FakeAdapter:
        def with_timestamps(self):
            return "TIMESTAMPED"

    def load_model(name, **kwargs):
        calls.append((name, kwargs))
        return FakeAdapter()

    monkeypatch.setitem(sys.modules, "onnx_asr", SimpleNamespace(load_model=load_model))

    assert _load_parakeet("the-model") == "TIMESTAMPED"
    assert calls == [("the-model", {"providers": ["CPUExecutionProvider"]})]
