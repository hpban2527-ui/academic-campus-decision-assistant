"""Provider-neutral contracts and safe public errors for preference AI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from personalization.models import StudentPreference


@dataclass(frozen=True)
class ProviderHealth:
    available: bool
    provider: str
    model: str
    code: str | None = None
    message: str | None = None


class PreferenceProviderError(RuntimeError):
    def __init__(self, code: str, public_message: str) -> None:
        super().__init__(public_message)
        self.code = code
        self.public_message = public_message


class PreferenceProviderUnavailable(PreferenceProviderError):
    """The local/cloud AI service cannot currently be reached or used."""


class PreferenceProviderInvalidResponse(PreferenceProviderError):
    """The AI replied, but the response cannot pass the trusted contract."""


class PreferenceAIProvider(Protocol):
    provider_name: str
    model: str

    def health(self) -> ProviderHealth:
        ...

    def interpret(self, text: str) -> StudentPreference:
        ...
