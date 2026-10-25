import pytest

from app.services.output_language import with_output_language


def test_auto_leaves_existing_prompt_unchanged():
    prompt = "Answer in the language of the question."

    assert with_output_language(prompt, "auto") == prompt
    assert with_output_language(prompt, None) == prompt


@pytest.mark.parametrize(
    ("language", "label"),
    [
        ("en", "English"),
        ("zh-Hant", "Traditional Chinese"),
        ("zh-Hans", "Simplified Chinese"),
        ("ja", "Japanese"),
        ("ko", "Korean"),
        ("es", "Spanish"),
        ("fr", "French"),
        ("de", "German"),
    ],
)
def test_fixed_language_adds_one_clear_instruction(language, label):
    prompt = "Existing prompt"

    result = with_output_language(prompt, language)

    assert result.startswith(prompt)
    assert f"Write all generated output in {label}." in result
    assert (
        "Do not switch languages based on the source material or input language."
        in result
    )
