"""He says "um" and "uh" while he thinks, and the model writes both down. These pin
what is dropped from a transcript before it is stored — and, just as much, what is
left alone: every real word, and the sentence shape around the sound that went."""
from highdeas.hesitation import without_hesitations


def test_a_hesitation_mid_sentence_is_dropped():
    assert without_hesitations(["I", "was", "um", "thinking"]) == (
        (0, "I"), (1, "was"), (3, "thinking"))


def test_a_hesitation_that_opened_the_note_hands_on_its_capital():
    # A third of the ones he says open a sentence. Drop the sound and nothing else,
    # and the note starts lowercase — which reads as a bug in the transcript.
    assert without_hesitations(["Um", "okay,", "another", "thing."]) == (
        (1, "Okay,"), (2, "another"), (3, "thing."))


def test_a_hesitation_after_a_full_stop_hands_on_its_capital_too():
    # Mid-note the sound comes far more often after a sentence has ended than at the
    # very top of one, so opening a note is not the only place a capital is owed.
    assert without_hesitations(["Done.", "uh", "then", "sleep."]) == (
        (0, "Done."), (2, "Then"), (3, "sleep."))


def test_a_bullet_between_the_full_stop_and_the_sound_does_not_hide_it():
    # A dictated list comes back a line per item, each opened by a "-". The sound
    # still opened that sentence, and the item still owes its capital.
    assert without_hesitations(["-", "Um", "take", "out", "trash."]) == (
        (0, "-"), (2, "Take"), (3, "out"), (4, "trash."))


def test_the_comma_the_model_set_the_sound_off_with_goes_with_it():
    # The pause gets punctuated as often as not. The comma was the sound's, not the
    # sentence's, so leaving it behind strands it against the word before.
    assert without_hesitations(["Um,", "okay."]) == ((1, "Okay."),)


def test_a_real_word_that_merely_starts_with_the_sound_is_left_alone():
    # Only a whole word of it is the sound. Nothing else in the note is worth the
    # risk of eating a word he actually said.
    said = ["An", "umbrella", "for", "Uma", "uh-huh"]
    assert without_hesitations(said) == tuple(enumerate(said))


def test_the_sound_is_the_same_sound_however_long_he_held_it():
    # The model spells a held sound out at the length it was held — it is why the
    # humming this note might have been is matched by shape and not by a list.
    assert without_hesitations(["Ummm", "yeah,", "uhhh", "maybe."]) == (
        (1, "Yeah,"), (3, "maybe."))


def test_a_note_of_nothing_but_hesitation_keeps_none_of_it():
    # Said aloud and thought better of. What is left is empty, and empty is a state
    # the transcript already knows how to show.
    assert without_hesitations(["Um,", "uh."]) == ()
