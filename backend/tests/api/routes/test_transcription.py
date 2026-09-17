"""Dictating a note: what is charged, what is refused, what is kept.

The wire format is stubbed with `respx` rather than mocked at the client, so
these also pin the thing that is easy to get wrong by accident - which numbers
out of a provider's response end up on the bill.
"""

from __future__ import annotations

import uuid
from collections.abc import Generator
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlmodel import Session, col, select

from app.core.config import settings
from app.models import UsageDaily, UsageFeature, UsageKind, User
from app.services import credits
from tests.utils.kb import API, create_user_with_password, login

VOICE = f"{API}/notes/voice"
TRANSCRIBE = f"{API}/notes/transcriptions"
UPSTREAM = "https://asr.test/v1/audio/transcriptions"

RECORDING = ("recording.webm", b"\x1a\x45\xdf\xa3fake-opus", "audio/webm")


@pytest.fixture
def configured() -> Generator[None]:
    """A deployment with dictation switched on."""
    model, base = settings.TRANSCRIPTION_MODEL, settings.TRANSCRIPTION_BASE_URL
    settings.TRANSCRIPTION_MODEL = "openai/whisper-large-v3-turbo"
    settings.TRANSCRIPTION_BASE_URL = "https://asr.test/v1"  # type: ignore[assignment]
    yield
    settings.TRANSCRIPTION_MODEL, settings.TRANSCRIPTION_BASE_URL = model, base


@pytest.fixture
def speaker(client: TestClient, db: Session) -> tuple[User, dict[str, str]]:
    user, password = create_user_with_password(db)
    return user, login(client, user, password)


def reply(**overrides: Any) -> dict[str, Any]:
    body = {"text": "  Buy oat milk and call the plumber.  ", "duration": 7.2}
    body.update(overrides)
    return body


def rows(db: Session, user_id: uuid.UUID) -> list[UsageDaily]:
    return list(
        db.exec(select(UsageDaily).where(col(UsageDaily.user_id) == user_id)).all()
    )


def test_it_says_so_when_nobody_configured_a_model(
    client: TestClient, speaker: tuple[User, dict[str, str]]
) -> None:
    """503 and a switched-off button, rather than a microphone that fails."""
    _, headers = speaker
    settings_view = client.get(VOICE, headers=headers).json()
    assert settings_view["enabled"] is False

    response = client.post(
        TRANSCRIBE, headers=headers, files={"file": RECORDING}, data={"seconds": "5"}
    )
    assert response.status_code == 503


@pytest.mark.usefixtures("configured")
def test_the_words_come_back_and_the_seconds_are_billed(
    client: TestClient, db: Session, speaker: tuple[User, dict[str, str]]
) -> None:
    user, headers = speaker
    with respx.mock:
        respx.post(UPSTREAM).mock(return_value=httpx.Response(200, json=reply()))
        response = client.post(
            TRANSCRIBE,
            headers=headers,
            files={"file": RECORDING},
            data={"seconds": "7", "language": "en"},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["text"] == "Buy oat milk and call the plumber."
    # 7.2 seconds is charged as 8: part of a second is a second.
    assert body["seconds"] == 8
    assert body["credits"] == pytest.approx(8 * credits.PER_AUDIO_SECOND / 1000)

    billed = [r for r in rows(db, user.id) if r.kind == UsageKind.transcribe]
    assert len(billed) == 1
    assert billed[0].feature == UsageFeature.voice
    assert billed[0].audio_seconds == 8
    assert billed[0].requests == 1


@pytest.mark.usefixtures("configured")
def test_a_provider_that_also_counts_tokens_does_not_bill_twice(
    client: TestClient, db: Session, speaker: tuple[User, dict[str, str]]
) -> None:
    """The trap this feature was written around.

    An audio response carries `input_tokens` / `output_tokens`; the usage
    reader looks for `prompt_tokens` / `completion_tokens`. Different keys, so
    the seconds are the whole bill - and this is the test that says it stays
    that way if somebody ever "tidies up" those names.
    """
    user, headers = speaker
    with respx.mock:
        respx.post(UPSTREAM).mock(
            return_value=httpx.Response(
                200,
                json=reply(
                    usage={"input_tokens": 4000, "output_tokens": 900, "seconds": 7.2}
                ),
            )
        )
        response = client.post(
            TRANSCRIBE,
            headers=headers,
            files={"file": RECORDING},
            data={"seconds": "7"},
        )

    assert response.status_code == 200
    billed = [r for r in rows(db, user.id) if r.kind == UsageKind.transcribe][0]
    assert (billed.input_tokens, billed.output_tokens) == (0, 0)
    assert billed.audio_seconds == 8

    spent = credits.spent_milli(db, user.id)
    assert spent == 8 * credits.PER_AUDIO_SECOND


@pytest.mark.usefixtures("configured")
def test_a_recording_with_no_duration_is_billed_on_what_the_browser_measured(
    client: TestClient, db: Session, speaker: tuple[User, dict[str, str]]
) -> None:
    user, headers = speaker
    with respx.mock:
        respx.post(UPSTREAM).mock(
            return_value=httpx.Response(200, json={"text": "Short one."})
        )
        response = client.post(
            TRANSCRIBE,
            headers=headers,
            files={"file": RECORDING},
            data={"seconds": "3"},
        )

    assert response.json()["seconds"] == 3
    billed = [r for r in rows(db, user.id) if r.kind == UsageKind.transcribe][0]
    assert billed.audio_seconds == 3


@pytest.mark.usefixtures("configured")
def test_nothing_is_billed_for_a_call_that_failed(
    client: TestClient, db: Session, speaker: tuple[User, dict[str, str]]
) -> None:
    user, headers = speaker
    with respx.mock:
        respx.post(UPSTREAM).mock(return_value=httpx.Response(500, text="model down"))
        response = client.post(
            TRANSCRIBE,
            headers=headers,
            files={"file": RECORDING},
            data={"seconds": "5"},
        )

    assert response.status_code == 502
    billed = [r for r in rows(db, user.id) if r.kind == UsageKind.transcribe]
    assert billed and billed[0].failures == 1
    assert billed[0].audio_seconds == 0
    assert credits.spent_milli(db, user.id) == 0


@pytest.mark.usefixtures("configured")
def test_an_empty_recording_is_refused_before_the_model_is_called(
    client: TestClient, speaker: tuple[User, dict[str, str]]
) -> None:
    _, headers = speaker
    with respx.mock:
        route = respx.post(UPSTREAM).mock(
            return_value=httpx.Response(200, json=reply())
        )
        response = client.post(
            TRANSCRIBE,
            headers=headers,
            files={"file": ("recording.webm", b"", "audio/webm")},
            data={"seconds": "0"},
        )
    assert response.status_code == 422
    assert not route.called


@pytest.mark.usefixtures("configured")
def test_an_over_long_recording_is_refused(
    client: TestClient, speaker: tuple[User, dict[str, str]]
) -> None:
    """Two limits, and the byte count is the one that actually binds.

    The duration the browser reports is a claim; the upload size is a fact.
    """
    _, headers = speaker
    oversize = b"0" * (settings.MAX_AUDIO_UPLOAD_MB * 1024 * 1024 + 10)
    with respx.mock:
        route = respx.post(UPSTREAM).mock(
            return_value=httpx.Response(200, json=reply())
        )
        too_big = client.post(
            TRANSCRIBE,
            headers=headers,
            files={"file": ("recording.webm", oversize, "audio/webm")},
            data={"seconds": "10"},
        )
        too_long = client.post(
            TRANSCRIBE,
            headers=headers,
            files={"file": RECORDING},
            data={"seconds": str(settings.MAX_AUDIO_SECONDS + 1)},
        )
    assert too_big.status_code == 413
    assert too_long.status_code == 413
    assert not route.called


@pytest.mark.usefixtures("configured")
def test_it_returns_text_rather_than_writing_a_note(
    client: TestClient, speaker: tuple[User, dict[str, str]]
) -> None:
    """The reason the endpoint has this shape: there is nothing to half-do."""
    _, headers = speaker
    before = client.get(f"{API}/notes/", headers=headers).json()["count"]
    with respx.mock:
        respx.post(UPSTREAM).mock(return_value=httpx.Response(200, json=reply()))
        client.post(
            TRANSCRIBE,
            headers=headers,
            files={"file": RECORDING},
            data={"seconds": "7"},
        )
    after = client.get(f"{API}/notes/", headers=headers).json()["count"]
    assert after == before


@pytest.mark.usefixtures("configured")
def test_what_the_microphone_button_is_told(
    client: TestClient, speaker: tuple[User, dict[str, str]]
) -> None:
    _, headers = speaker
    body = client.get(VOICE, headers=headers).json()
    assert body["enabled"] is True
    assert body["max_seconds"] == settings.MAX_AUDIO_SECONDS
    # About a credit a minute - the sentence the rate was chosen to make true.
    assert 1.0 <= body["credits_per_minute"] <= 1.5
