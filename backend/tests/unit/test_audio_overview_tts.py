def test_kokoro_english_phonemizer_loads_and_tokenizes():
    from misaki.en import G2P

    phonemes, tokens = G2P(trf=False, british=False, fallback=None)(
        "The two hosts discuss their sources."
    )

    assert phonemes
    assert tokens
