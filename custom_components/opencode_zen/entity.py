"""Base entity for OpenCode Zen (Responses API with SSE streaming)."""

import asyncio
import base64
import json
import logging
import mimetypes
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any, cast

import aiohttp

from homeassistant.components import conversation
from homeassistant.config_entries import ConfigSubentry
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, llm
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.json import json_dumps
from probatio import to_openapi

from . import OpencodeZenConfigEntry
from .api import api_error_handler, response_error_key
from .const import (
    CONF_CHAT_MODEL,
    CONF_MAX_TOKENS,
    CONF_REQUIRE_CONFIRMATION,
    CONF_TEMPERATURE,
    CONF_TOP_P,
    DEFAULT_MODEL,
    DOMAIN,
    LOGGER,
    MAX_TOOL_ITERATIONS,
    RECOMMENDED_MAX_TOKENS,
    RECOMMENDED_TEMPERATURE,
    RECOMMENDED_TOP_P,
)

_LOGGER = logging.getLogger(__name__)

SAFETY_INSTRUCTIONS = (
    "Safety rule: before using a tool that changes security-relevant state "
    "(locks, alarm control panels, garage doors), always ask the user for "
    "confirmation in their language and wait for approval, unless the user "
    "explicitly asked for immediate action. Ordinary queries, lights and "
    "informational answers need no confirmation."
)


def _format_tool(tool: llm.Tool, custom_serializer: Any | None) -> dict[str, Any]:
    params = to_openapi(tool.parameters, custom_serializer=custom_serializer)
    spec: dict[str, Any] = {"name": tool.name, "parameters": params}
    if tool.description:
        spec["description"] = tool.description
    return {"type": "function", "name": tool.name, "description": tool.description or "", "parameters": params}


def _decode_args(arguments: str) -> Any:
    try:
        return json.loads(arguments) if arguments else {}
    except json.JSONDecodeError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="json_parse_error",
            translation_placeholders={"message": str(err)},
        ) from err


def _content_to_input_item(content: conversation.Content) -> dict[str, Any] | None:
    if isinstance(content, conversation.ToolResultContent):
        return {
            "type": "function_call_output",
            "call_id": content.tool_call_id,
            "output": json_dumps(content.tool_result),
        }
    role = content.role
    text = content.content or ""
    if isinstance(content, conversation.SystemContent):
        return {"role": "system", "content": text} if text else None
    if role == "user":
        return {"role": "user", "content": text} if text else None
    if role == "assistant":
        item: dict[str, Any] = {"role": "assistant", "content": text}
        return item
    LOGGER.warning("Skipping unsupported content: %s", type(content))
    return None


def _assistant_content_to_input(content: conversation.Content) -> dict[str, Any] | None:
    return _content_to_input_item(content)


async def async_prepare_images_for_prompt(
    hass: Any, files: list[Path]
) -> list[dict[str, Any]]:
    """Read image attachments as Responses input_image parts (executor job)."""

    def _read() -> list[dict[str, Any]]:
        parts: list[dict[str, Any]] = []
        for file_path in files:
            if not file_path.exists():
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="api_error",
                    translation_placeholders={
                        "message": f"Attachment not found: {file_path}"
                    },
                )
            mime_type, _ = mimetypes.guess_type(str(file_path))
            if not mime_type or not mime_type.startswith("image/"):
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="api_error",
                    translation_placeholders={
                        "message": f"Only images are supported: {file_path}"
                    },
                )
            data = base64.b64encode(file_path.read_bytes()).decode("utf-8")
            parts.append(
                {
                    "type": "input_image",
                    "image_url": f"data:{mime_type};base64,{data}",
                    "detail": "auto",
                }
            )
        return parts

    return await hass.async_add_executor_job(_read)


async def _transform_response(
    output: list[dict[str, Any]],
) -> AsyncGenerator[conversation.AssistantContentDeltaDict]:
    text_parts: list[str] = []
    tool_calls: list[llm.ToolInput] = []
    for item in output:
        item_type = item.get("type")
        if item_type == "message":
            for part in item.get("content", []):
                if part.get("type") in ("output_text", "text") and part.get("text"):
                    text_parts.append(part["text"])
        elif item_type == "function_call":
            tool_calls.append(
                llm.ToolInput(
                    id=item.get("call_id") or item.get("id", ""),
                    tool_name=item.get("name", ""),
                    tool_args=_decode_args(item.get("arguments", "") or ""),
                )
            )
    data: conversation.AssistantContentDeltaDict = {"role": "assistant"}
    if text_parts:
        data["content"] = "".join(text_parts)
    if tool_calls:
        data["tool_calls"] = tool_calls
    yield data


async def _transform_response_stream(
    body: aiohttp.StreamReader, collector: dict[str, Any]
) -> AsyncGenerator[conversation.AssistantContentDeltaDict]:
    """Transform an OpenAI Responses SSE stream into HA deltas.

    Fills collector with full text + completed function_call items so the
    caller can rebuild history for the next tool iteration.
    """
    yield {"role": "assistant"}
    event_name: str | None = None
    text_parts: list[str] = []
    func_calls: list[dict[str, Any]] = []

    while True:
        raw = await body.readline()
        if not raw:
            break
        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            event_name = None
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_name = line[6:].strip()
            continue
        if not line.startswith("data:"):
            continue
        data_str = line[5:].strip()
        if data_str == "[DONE]":
            break
        try:
            event = json.loads(data_str)
        except ValueError:
            LOGGER.debug("Skipping non-JSON SSE data")
            continue
        ev = event_name or event.get("type", "")

        if ev == "response.output_text.delta":
            delta = event.get("delta", "")
            if delta:
                text_parts.append(delta)
                yield {"content": delta}
        elif ev == "response.output_item.done":
            item = event.get("item") or {}
            if item.get("type") == "function_call":
                func_calls.append(item)
                try:
                    args = _decode_args(item.get("arguments", "") or "")
                except HomeAssistantError:
                    LOGGER.warning("Dropping function call with bad arguments")
                    continue
                yield {
                    "tool_calls": [
                        llm.ToolInput(
                            id=item.get("call_id") or item.get("id", ""),
                            tool_name=item.get("name", ""),
                            tool_args=args,
                        )
                    ]
                }
        elif ev in ("response.completed", "response.failed", "response.incomplete"):
            if ev != "response.completed":
                LOGGER.warning("Responses stream ended with %s", ev)
            break
        # ignore the rest: response.created, output_item.added, content deltas, etc.

    collector["text"] = "".join(text_parts)
    collector["function_calls"] = func_calls


class OpencodeZenBaseLLMEntity(Entity):
    """Shared Responses chat loop."""

    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, entry: OpencodeZenConfigEntry, subentry: ConfigSubentry) -> None:
        self.entry = entry
        self.subentry = subentry
        self._attr_unique_id = subentry.subentry_id
        self._attr_device_info = dr.DeviceInfo(
            identifiers={(DOMAIN, subentry.subentry_id)},
            name=subentry.title,
            manufacturer="OpenCode Zen",
            model=subentry.data.get(CONF_CHAT_MODEL, DEFAULT_MODEL),
            entry_type=dr.DeviceEntryType.SERVICE,
        )

    async def _async_handle_chat_log(
        self,
        chat_log: conversation.ChatLog,
        structure: Any | None = None,
    ) -> None:
        options = self.subentry.data
        entry_data = self.entry.data
        base_url = str(entry_data.get("base_url", "")).rstrip("/")
        api_key = str(entry_data.get("api_key", ""))
        model: str = options.get(CONF_CHAT_MODEL, DEFAULT_MODEL)

        tools: list[dict[str, Any]] | None = None
        if chat_log.llm_api:
            tools = [
                _format_tool(tool, chat_log.llm_api.custom_serializer)
                for tool in chat_log.llm_api.tools
            ]

        input_items: list[dict[str, Any]] = [
            m for content in chat_log.content if (m := _content_to_input_item(content))
        ]
        last_content = chat_log.content[-1]
        if (
            isinstance(last_content, conversation.UserContent)
            and last_content.attachments
        ):
            image_parts = await async_prepare_images_for_prompt(
                self.hass, [a.path for a in last_content.attachments]
            )
            for i in range(len(input_items) - 1, -1, -1):
                if input_items[i].get("role") == "user":
                    parts: list[dict[str, Any]] = []
                    text = input_items[i].get("content", "")
                    if isinstance(text, str) and text:
                        parts.append({"type": "input_text", "text": text})
                    parts.extend(image_parts)
                    input_items[i] = {"role": "user", "content": parts}
                    break
        instructions = ""
        for content in chat_log.content:
            if isinstance(content, conversation.SystemContent) and content.content:
                instructions = content.content
                break
        if options.get(CONF_REQUIRE_CONFIRMATION, True) and structure is None:
            instructions = (
                f"{instructions}\n{SAFETY_INSTRUCTIONS}"
                if instructions
                else SAFETY_INSTRUCTIONS
            )

        session = async_get_clientsession(self.hass)
        url = f"{base_url}/responses"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "homeassistant-opencode-zen/0.3.0",
            "x-opencode-session": chat_log.conversation_id,
        }

        for _iteration in range(MAX_TOOL_ITERATIONS):
            payload: dict[str, Any] = {
                "model": model,
                "input": input_items,
                "store": False,
                "stream": True,
            }
            if instructions:
                payload["instructions"] = instructions
            if tools:
                payload["tools"] = tools
                payload["tool_choice"] = "auto"
            if CONF_MAX_TOKENS in options:
                payload["max_output_tokens"] = int(options.get(CONF_MAX_TOKENS, RECOMMENDED_MAX_TOKENS))
            else:
                payload["max_output_tokens"] = RECOMMENDED_MAX_TOKENS
            if CONF_TEMPERATURE in options:
                payload["temperature"] = float(options.get(CONF_TEMPERATURE, RECOMMENDED_TEMPERATURE))
            if CONF_TOP_P in options:
                payload["top_p"] = float(options.get(CONF_TOP_P, RECOMMENDED_TOP_P))
            if structure is not None:
                # Note: strict json_schema output makes reasoning models stall
                # (no first byte for minutes), so request JSON via instructions
                # and parse it in ai_task.py instead.
                try:
                    schema = to_openapi(
                        structure,
                        custom_serializer=(
                            chat_log.llm_api.custom_serializer
                            if chat_log.llm_api
                            else None
                        ),
                    )
                    json_hint = (
                        "Return only a valid JSON object matching this JSON "
                        f"schema, no other text: {json_dumps(schema)}"
                    )
                    key_names = ", ".join(
                        (schema.get("properties") or {}).keys()
                    )
                    if key_names:
                        json_hint += (
                            " Use EXACTLY these key names, do not translate, "
                            f"rename or add diacritics: {key_names}."
                        )
                except Exception:  # noqa: BLE001
                    LOGGER.warning("Could not convert AI task structure, falling back")
                    json_hint = "Return only valid JSON."
                payload["instructions"] = (
                    f"{instructions}\n{json_hint}" if instructions else json_hint
                )

            with api_error_handler():
                async with session.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=900, sock_read=300),
                ) as resp:
                    if resp.status in (401, 403):
                        raise HomeAssistantError(
                            translation_domain=DOMAIN,
                            translation_key="invalid_auth",
                            translation_placeholders={"message": f"HTTP {resp.status}"},
                        )
                    if resp.status >= 400:
                        text = (await resp.text())[:1000]
                        raise HomeAssistantError(
                            translation_domain=DOMAIN,
                            translation_key=response_error_key(resp.status, text),
                            translation_placeholders={"message": f"HTTP {resp.status}: {text}"},
                        )
                    collector: dict[str, Any] = {"text": "", "function_calls": []}
                    try:
                        messages = [
                            msg
                            async for content in chat_log.async_add_delta_content_stream(
                                self.entity_id,
                                _transform_response_stream(resp.content, collector),
                            )
                            if (msg := _assistant_content_to_input(content))
                        ]
                    except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as err:
                        if collector["text"] or collector["function_calls"]:
                            raise HomeAssistantError(
                                translation_domain=DOMAIN,
                                translation_key="api_error",
                                translation_placeholders={
                                    "message": f"stream interrupted: {err}"
                                },
                            ) from err
                        LOGGER.warning(
                            "Responses stream failed, retrying non-streaming: %s", err
                        )
                        payload["stream"] = False
                        async with session.post(
                            url, headers=headers, json=payload, timeout=300
                        ) as retry_resp:
                            if retry_resp.status >= 400:
                                err_text = (await retry_resp.text())[:1000]
                                raise HomeAssistantError(
                                    translation_domain=DOMAIN,
                                    translation_key=response_error_key(
                                        retry_resp.status, err_text
                                    ),
                                    translation_placeholders={
                                        "message": f"HTTP {retry_resp.status}: {err_text}"
                                    },
                                )
                            data = await retry_resp.json()
                        output = data.get("output", [])
                        input_items.extend(output)
                        messages = [
                            msg
                            async for content in chat_log.async_add_delta_content_stream(
                                self.entity_id,
                                _transform_response(
                                    cast(list[dict[str, Any]], output)
                                ),
                            )
                            if (msg := _assistant_content_to_input(content))
                        ]

            if collector["text"]:
                input_items.append(
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {"type": "output_text", "text": collector["text"]}
                        ],
                    }
                )
            input_items.extend(collector["function_calls"])
            input_items.extend([m for m in messages if m.get("type") == "function_call_output"])

            if not chat_log.unresponded_tool_results:
                break
