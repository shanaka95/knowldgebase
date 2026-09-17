"""Speech to text, for dictating a note.

The endpoint is OpenAI's ``/audio/transcriptions``: a multipart POST with the
recording and a model name, and a JSON body with the words in it. Every hosted
provider and every local server implements it identically, so this is a base
URL and a key away from running anywhere.

Three decisions are worth the ink:

**Nothing is stored.** The recording exists for the length of one request and
is then gone. The value is the text; a voice is personal data of a kind that
brings retention and deletion obligations with it; and notes are private, so
there is no case for keeping the audio to listen to later.

**It is synchronous.** A job table, a claim function and a worker budget for a
call that takes a few seconds would be machinery in place of an await. The
duration cap is what keeps that honest, and it is enforced twice - the browser
stops recording, and this refuses anything longer.

**Billing is per second**, which is how the providers price it, and the caller
is told the duration so the same number reaches the meter and the person.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from app.core.config import settings
from app.models import UsageKind
from app.services.model_client import ModelServerError, auth_headers
from app.services.usage import UsageMeter, read_usage, response_model

logger = logging.getLogger(__name__)


class TranscriptionError(ModelServerError):
    """The recording could not be turned into words."""


@dataclass(frozen=True, slots=True)
class Transcript:
    """What was said, how long it took to say, and what listened."""

    text: str
    seconds: int
    model: str


def _billable_seconds(reported: float, fallback: int) -> int:
    """Whole seconds, rounded up, never zero.

    Providers differ over whether they report a duration at all, so a caller's
    own measurement stands in. Rounding up means a run of very short recordings
    costs what it should rather than nothing.
    """
    value = reported if reported > 0 else float(fallback)
    return max(1, -(-int(value * 1000) // 1000))


class TranscriptionClient:
    """An OpenAI-compatible ``/audio/transcriptions`` endpoint."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = (base_url or str(settings.TRANSCRIPTION_BASE_URL or "")).rstrip(
            "/"
        )
        self.model = model or settings.TRANSCRIPTION_MODEL
        self.api_key = settings.TRANSCRIPTION_API_KEY if api_key is None else api_key
        self._client = client
        self._owns_client = client is None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    connect=10.0,
                    read=settings.TRANSCRIPTION_TIMEOUT_SECONDS,
                    write=60.0,
                    pool=10.0,
                ),
                headers=auth_headers(self.api_key),
            )
        return self._client

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def transcribe(
        self,
        audio: bytes,
        *,
        filename: str = "recording.webm",
        content_type: str = "audio/webm",
        language: str | None = None,
        duration_hint: int = 0,
        meter: UsageMeter | None = None,
    ) -> Transcript:
        """The words in a recording.

        ``duration_hint`` is what the browser measured, used for billing only
        when the provider reports no duration of its own.
        """
        if not settings.transcription_enabled:
            raise TranscriptionError("transcription: no model is configured")

        form: dict[str, str] = {"model": self.model}
        if language:
            # Given, not guessed. Detection is the model's job and it is good
            # at it; a wrong hint is worse than none.
            form["language"] = language

        # Not retried on a cold start, unlike the JSON calls: a retry would
        # upload the whole recording again, and a person is waiting.
        try:
            response = await self.client.post(
                f"{self.base_url}/audio/transcriptions",
                data=form,
                files={"file": (filename, audio, content_type)},
            )
        except httpx.HTTPError as exc:
            if meter is not None:
                meter.failure(UsageKind.transcribe, self.model)
            raise TranscriptionError(f"transcription: {exc}") from exc

        if response.status_code >= 400:
            if meter is not None:
                meter.failure(UsageKind.transcribe, self.model)
            raise TranscriptionError(
                f"transcription: HTTP {response.status_code}: {response.text[:300]}"
            )

        try:
            data = response.json()
            text = str(data["text"]).strip()
        except (ValueError, KeyError, TypeError) as exc:
            if meter is not None:
                meter.failure(UsageKind.transcribe, self.model)
            raise TranscriptionError(
                f"transcription: malformed response: {response.text[:300]}"
            ) from exc

        reported = data.get("duration") if isinstance(data, dict) else None
        seconds = _billable_seconds(
            float(reported) if isinstance(reported, int | float) else 0.0,
            duration_hint,
        )

        if meter is not None:
            # `read_usage` fills what the provider sent; the duration is
            # authoritative here because it is what the bill is drawn on and
            # not every provider puts it in the usage block.
            counts = read_usage(data)
            counts.audio_seconds = seconds
            meter.record_counts(
                UsageKind.transcribe, response_model(data, self.model), counts
            )

        return Transcript(
            text=text, seconds=seconds, model=response_model(data, self.model)
        )
