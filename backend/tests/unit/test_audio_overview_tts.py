def test_kokoro_english_phonemizer_loads_and_tokenizes():
    from kokoro import KPipeline

    pipeline = KPipeline(lang_code="a", model=False)
    assert pipeline.g2p.fallback is not None

    phonemes, tokens = pipeline.g2p("Qrrblax")
    assert phonemes
    assert tokens
