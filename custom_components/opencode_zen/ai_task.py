"""AI Task support for OpenCode Zen (text data only, v1)."""

from typing import override

from homeassistant.components import ai_task, conversation
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import OpencodeZenConfigEntry
from .const import DOMAIN, LOGGER
from .entity import OpencodeZenBaseLLMEntity


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: OpencodeZenConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up AI Task entities."""
    for subentry in config_entry.subentries.values():
        if subentry.subentry_type != "ai_task_data":
            continue
        async_add_entities(
            [OpencodeZenTaskEntity(config_entry, subentry)],
            config_subentry_id=subentry.subentry_id,
        )


class OpencodeZenTaskEntity(ai_task.AITaskEntity, OpencodeZenBaseLLMEntity):
    """OpenCode Zen AI Task entity."""

    def __init__(self, entry: OpencodeZenConfigEntry, subentry) -> None:
        """Initialize."""
        super().__init__(entry, subentry)
        self._attr_supported_features = (
            ai_task.AITaskEntityFeature.GENERATE_DATA
            | ai_task.AITaskEntityFeature.SUPPORT_ATTACHMENTS
        )

    @override
    async def _async_generate_data(
        self,
        task: ai_task.GenDataTask,
        chat_log: conversation.ChatLog,
    ) -> ai_task.GenDataTaskResult:
        """Generate data."""
        await self._async_handle_chat_log(chat_log, task.structure)
        last = chat_log.content[-1]
        if not isinstance(last, conversation.AssistantContent):
            LOGGER.error("Last content is not AssistantContent: %s", last)
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="api_error",
                translation_placeholders={"message": "empty response"},
            )
        text = last.content or ""
        LOGGER.debug("AI task raw response: %s", text[:500])
        if not task.structure:
            return ai_task.GenDataTaskResult(
                conversation_id=chat_log.conversation_id, data=text
            )
        import json as _json

        try:
            data = _json.loads(text)
        except ValueError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="api_error",
                translation_placeholders={"message": f"invalid JSON: {err}"},
            ) from err
        return ai_task.GenDataTaskResult(
            conversation_id=chat_log.conversation_id, data=data
        )
