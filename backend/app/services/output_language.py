"""Shared instructions for generated project output languages."""
from typing import Optional


_LANGUAGES = {
    "en": "English",
    "zh-Hant": "Traditional Chinese",
    "zh-Hans": "Simplified Chinese",
    "ja": "Japanese",
    "ko": "Korean",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
}


def with_output_language(prompt: str, language: Optional[str]) -> str:
    """Append one language rule, leaving automatic output unchanged.

    Args:
        prompt: The existing generation prompt.
        language: A supported language code, ``auto``, or None for legacy rows.

    Returns:
        The original prompt in automatic mode, otherwise the prompt with a
        fixed language instruction appended.
    """
    label = _LANGUAGES.get(language or "")
    if label is None:
        return prompt
    return (
        f"{prompt}\n\nWrite all generated output in {label}. "
        "Do not switch languages based on the source material or input language."
    )
