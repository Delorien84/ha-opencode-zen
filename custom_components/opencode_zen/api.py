"""API client helper for OpenCode Zen (Responses API via aiohttp)."""

from collections.abc import Generator, Mapping
from contextlib import contextmanager
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DEFAULT_BASE_URL, DEFAULT_MODEL, DOMAIN, RECOMMENDED_CHAT_MODELS

_LOGGER = logging.getLogger(__name__)


USER_AGENT = "homeassistant-opencode-zen/0.3.0"


def _headers(api_key: str, session_id: str | None = None) -> dict[str, str]:
    # Mandatory auth header (previously injected via NodeRED) + Go session
    # affinity header (x-opencode-session) + own User-Agent per Go docs.
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    }
    if session_id:
        headers["x-opencode-session"] = session_id
    return headers


def _base_url(data: Mapping[str, Any]) -> str:
    return str(data.get("base_url", DEFAULT_BASE_URL)).rstrip("/")


def _api_key(data: Mapping[str, Any]) -> str:
    return str(data.get("api_key", ""))


def response_error_key(status: int, body: str) -> str:
    """Map a Responses API failure to a translation key."""
    if "FreeTierError" in body:
        return "free_tier"
    if status == 404 or "model_not_found" in body:
        return "model_not_found"
    return "api_error"


@contextmanager
def api_error_handler() -> Generator[None]:
    """Translate transport/API errors to HomeAssistantError."""
    try:
        yield
    except HomeAssistantError:
        raise
    except TimeoutError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="timeout",
            translation_placeholders={"message": str(err)},
        ) from err
    except OSError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
            translation_placeholders={"message": str(err)},
        ) from err


async def async_list_models(hass: HomeAssistant, data: Mapping[str, Any]) -> list[str]:
    """List models from GET {base}/models."""
    session = async_get_clientsession(hass)
    url = f"{_base_url(data)}/models"
    with api_error_handler():
        async with session.get(
            url, headers=_headers(_api_key(data)), timeout=10
        ) as resp:
            if resp.status in (401, 403):
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="invalid_auth",
                    translation_placeholders={"message": f"HTTP {resp.status}"},
                )
            if resp.status == 402:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="quota_exceeded",
                    translation_placeholders={"message": f"HTTP {resp.status}"},
                )
            if resp.status >= 400:
                body = (await resp.text())[:500]
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="api_error",
                    translation_placeholders={"message": f"HTTP {resp.status}: {body}"},
                )
            payload = await resp.json()
    models: list[str] = []
    for item in payload.get("data", []):
        model_id = item.get("id")
        if model_id:
            models.append(model_id)
    return models or list(RECOMMENDED_CHAT_MODELS)


async def async_validate_responses(
    hass: HomeAssistant, data: Mapping[str, Any], model: str
) -> None:
    """Validate POST {base}/responses with a minimal request."""
    session = async_get_clientsession(hass)
    url = f"{_base_url(data)}/responses"
    body = {
        "model": model or DEFAULT_MODEL,
        "input": "Reply with the word ok.",
        "max_output_tokens": 32,
        "store": False,
        "stream": False,
    }
    with api_error_handler():
        async with session.post(
            url,
            headers=_headers(_api_key(data), session_id="ha-config-validation"),
            json=body,
            timeout=30,
        ) as resp:
            if resp.status in (401, 403):
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="invalid_auth",
                    translation_placeholders={"message": f"HTTP {resp.status}"},
                )
            if resp.status >= 400:
                text = (await resp.text())[:1000]
                _LOGGER.error("Responses validation failed: %s", text)
                key = response_error_key(resp.status, text)
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key=key,
                    translation_placeholders={"message": f"HTTP {resp.status}: {text}"},
                )
            await resp.json()


def recommended_model(models: list[str] | None) -> str:
    """Pick preferred model."""
    if not models:
        return DEFAULT_MODEL
    for candidate in RECOMMENDED_CHAT_MODELS:
        if candidate in models:
            return candidate
    return models[0]


def model_name_to_title(model_id: str) -> str:
    """Convert model id to title."""
    words = model_id.replace("-", " ").replace("_", " ").replace("/", " ").split()
    return " ".join(word.capitalize() for word in words)
