"""When the model doesn't hear clean speech it doesn't fail quietly — it hands back
humming rendered as "Mm-hmm", or, on noise, a confident hallucination (often in
another script entirely). These pin how that raw text is relabelled so a note reads
`[singing]` or `[unclear]` instead — while leaving every real sentence untouched."""
from highdeas.nonspeech import SINGING, UNCLEAR, mark_nonspeech


def test_empty_transcript_reads_unclear():
    assert mark_nonspeech("") == UNCLEAR


def test_whitespace_and_punctuation_only_reads_unclear():
    assert mark_nonspeech("  ...  ") == UNCLEAR


def test_a_hummed_note_reads_as_singing():
    assert mark_nonspeech("Mm-hmm.") == SINGING


def test_a_page_of_la_reads_as_singing():
    assert mark_nonspeech("La la la la la la la la") == SINGING


def test_a_run_of_humming_before_speech_is_bracketed_in_place():
    assert mark_nonspeech("Mm-hmm mm-hmm mm mm mm mm That was singing.") == \
        "[singing] That was singing."


def test_a_hallucination_in_another_script_reads_unclear():
    assert mark_nonspeech("Бля бля бля бля") == UNCLEAR


def test_plain_speech_is_left_exactly_as_it_was():
    said = "Change sheets before Mo Rong arrives."
    assert mark_nonspeech(said) == said


def test_multiline_grouped_speech_keeps_its_newlines():
    said = "- Take out trash tomorrow.\n- Of course, nothing else."
    assert mark_nonspeech(said) == said


def test_um_and_uh_are_speech_not_humming():
    said = "Um okay, another test magic card thing."
    assert mark_nonspeech(said) == said


def test_a_lone_ambiguous_syllable_is_not_singing():
    # "La" alone could be a place or a name; only a run (or an unmistakable hum)
    # is safe to relabel, so a single one is left as the model heard it.
    assert mark_nonspeech("La.") == "La."


def test_humming_shorter_than_a_run_is_left_untouched():
    said = "Hmm, what the hell?"
    assert mark_nonspeech(said) == said


def test_accented_latin_is_not_mistaken_for_another_script():
    said = "Café Genau déjà vu."
    assert mark_nonspeech(said) == said
