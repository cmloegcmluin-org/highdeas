from highdeas.vocabulary import corrections, read_lexicon


def test_read_lexicon_takes_the_term_at_the_head_of_each_line(tmp_path):
    # The file is prose he keeps by hand: comments, blank lines, bullets, and a gloss
    # after the term. Only the term itself biases transcription.
    lexicon = tmp_path / "lexicon.md"
    lexicon.write_text(
        "# Douglas's lexicon\n"
        "\n"
        "Highdeas — his audio-memo web app\n"
        "Sagittal\n"
        "- Genau: German 'exactly'\n",
        encoding="utf-8")

    assert read_lexicon(lexicon) == ("Highdeas", "Sagittal", "Genau")


def test_read_lexicon_of_a_file_that_isnt_there_is_no_terms(tmp_path):
    # Most machines start without one, and the Mac may never get one. A missing
    # lexicon has to mean "correct nothing", not a transcription that dies.
    assert read_lexicon(tmp_path / "nothing-here.md") == ()


def test_corrections_names_the_word_to_swap_and_what_to_swap_it_for():
    # The model heard a term it doesn't know and wrote the nearest thing it does.
    assert corrections(["an", "idea", "for", "hideas"], ("Highdeas",)) == ((3, 1, "Highdeas"),)


def test_corrections_compares_the_bare_word_and_gives_its_punctuation_back():
    # A word at the end of a sentence carries a full stop. Compared with it, "hideas."
    # scores under the threshold and the term is missed; swapped without it, the note
    # loses the sentence break.
    assert corrections(["hideas."], ("Highdeas",)) == ((0, 1, "Highdeas."),)


def test_corrections_gathers_up_the_words_a_name_was_split_into():
    # A coined name is a compound, and the model knows the halves but not the whole,
    # so it writes them apart. Spelled out, the run is the term exactly: one
    # correction, covering both words.
    assert corrections(["a", "note", "in", "notes", "nook"],
                       ("Notesnook",)) == ((3, 2, "Notesnook"),)


def test_corrections_leaves_ordinary_words_that_merely_sound_like_a_term():
    # The words the model splits a name into are ordinary English, so a run of them
    # can only be gathered up when it spells the term outright: "fun times" is not
    # FunTime, and an evening that ends in a sauna did not end in Asana.
    assert corrections(["fun", "times"], ("FunTime",)) == ()
    assert corrections(["a", "sauna"], ("Asana",)) == ()


def test_corrections_leave_a_word_that_already_spells_the_term():
    # Half the names worth knowing are ordinary words too. The model spelled this one
    # right whichever was meant, so there is nothing to fix — capitalising it would be
    # an opinion about what he was talking about, and usually the wrong one.
    assert corrections(["an", "apple", "tree"], ("Apple",)) == ()


def test_corrections_only_guess_at_a_term_long_enough_for_a_guess_to_mean_anything():
    # Three letters is too few for "sounds like" to say anything: "note" scores 0.86
    # against the name "Noe", and "note" is the commonest word in a memo. Short names
    # are corrected toward only when they're spelled outright.
    assert corrections(["a", "note", "to", "self"], ("Noe",)) == ()
    assert corrections(["ask", "noe", "about", "it"], ("Noe",)) == ()


def test_corrections_leaves_a_whole_word_the_term_merely_contains():
    # He talks about harmonics constantly, and "harmonic" scores just over the
    # threshold against "xenharmonic" — one contains the other. A complete word the
    # term is built out of is a word he said, not a word the model fumbled.
    assert corrections(["the", "harmonic", "series"], ("xenharmonic",)) == ()


def test_corrections_never_gathers_words_across_a_sentence_break():
    # However alike the two halves sound joined up, nobody said a name across a full
    # stop — and gathering them would swallow the break between two sentences.
    assert corrections(["high.", "ideas"], ("Highdeas",)) == ()
