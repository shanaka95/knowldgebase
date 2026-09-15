"""Which language something is written in.

Two features need this and they need it differently. Ask wants the language of
a *question* - often three words long - so that the answer comes back in it
whatever language the pages are in. Translation wants the language of a *page*,
which is thousands of characters and never in doubt.

The hard case is the short one, and it is handled in two ways: the candidate
languages are restricted to the ones the product offers, which stops a
three-word question being matched against a hundred alternatives, and a
confidence floor means "I don't know" is an available answer. A caller that
gets ``None`` should do whatever it did before this existed rather than act on
a guess - telling a model to answer in Afrikaans because somebody typed "ok"
would be worse than not telling it anything.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache

logger = logging.getLogger(__name__)

# The languages the product offers to translate into, and therefore the only
# ones it tries to recognise. English names, because they are what the model is
# told to write in; the UI shows the endonym beside them.
LANGUAGES: dict[str, str] = {
    "en": "English",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "it": "Italian",
    "pt": "Portuguese",
    "nl": "Dutch",
    "pl": "Polish",
    "sv": "Swedish",
    "da": "Danish",
    "no": "Norwegian",
    "fi": "Finnish",
    "cs": "Czech",
    "ro": "Romanian",
    "hu": "Hungarian",
    "el": "Greek",
    "tr": "Turkish",
    "ru": "Russian",
    "uk": "Ukrainian",
    "ar": "Arabic",
    "he": "Hebrew",
    "hi": "Hindi",
    "id": "Indonesian",
    "vi": "Vietnamese",
    "th": "Thai",
    "zh": "Chinese",
    "ja": "Japanese",
    "ko": "Korean",
}

DEFAULT_LANGUAGE = "en"

# Below this the detector is guessing. Measured on short questions: a correct
# answer on a handful of words sits well above it, and the failures ("ok",
# "and in euros?" with no thread behind it) sit below.
MIN_CONFIDENCE = 0.5

# Shorter than this, a text says almost nothing about its language. Ask gets
# around it by detecting over the whole thread rather than the last question.
MIN_CHARS = 8

# A page does not need thousands of characters to be recognised, and feeding
# the whole of one to a bag-of-ngrams model is wasted work.
SAMPLE_CHARS = 4000


@dataclass(frozen=True, slots=True)
class Detected:
    code: str
    name: str
    confidence: float


@lru_cache(maxsize=1)
def _identifier():  # type: ignore[no-untyped-def]
    """The model, loaded once per process and restricted to our languages.

    Loading costs a moment and some memory, so it happens on the first
    detection rather than at import: a worker that only indexes never pays it.
    """
    from py3langid.langid import (  # type: ignore[import-untyped]
        MODEL_FILE,
        LanguageIdentifier,
    )

    identifier = LanguageIdentifier.from_model_file(MODEL_FILE, norm_probs=True)
    identifier.set_languages(list(LANGUAGES))
    return identifier


def detect(text: str, *, minimum: float = MIN_CONFIDENCE) -> Detected | None:
    """The language of ``text``, or ``None`` when it is not worth claiming."""
    sample = (text or "").strip()
    if len(sample) < MIN_CHARS:
        return None
    if len(sample) > SAMPLE_CHARS:
        sample = sample[:SAMPLE_CHARS]
    try:
        code, confidence = _identifier().classify(sample)
    except Exception:  # noqa: BLE001 - a missing model must not break a request
        logger.warning("language detection unavailable", exc_info=True)
        return None
    if code not in LANGUAGES or confidence < minimum:
        return None
    return Detected(code=code, name=LANGUAGES[code], confidence=float(confidence))


def language_name(code: str | None) -> str | None:
    """The English name of a language code, or None if we do not offer it."""
    return LANGUAGES.get((code or "").strip().lower()) or None


def is_supported(code: str | None) -> bool:
    return (code or "").strip().lower() in LANGUAGES
