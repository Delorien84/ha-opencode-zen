"""Config flow for OpenCode Zen."""

import logging
from typing import Any, override

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_API_KEY, CONF_LLM_HASS_API, CONF_PROMPT
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import llm
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TemplateSelector,
)

from .api import (
    async_list_models,
    async_validate_responses,
    model_name_to_title,
    recommended_model,
)
from .const import (
    CONF_BASE_URL,
    CONF_CHAT_MODEL,
    CONF_MAX_TOKENS,
    CONF_RECOMMENDED,
    CONF_REQUIRE_CONFIRMATION,
    CONF_TEMPERATURE,
    CONF_TOP_P,
    DEFAULT_BASE_URL,
    DOMAIN,
    LOGGER,
    RECOMMENDED_MAX_TOKENS,
    RECOMMENDED_TEMPERATURE,
    RECOMMENDED_TOP_P,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_BASE_URL, default=DEFAULT_BASE_URL): str,
        vol.Required(CONF_API_KEY): str,
    }
)


class OpencodeZenConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle config flow."""

    VERSION = 1

    data: dict[str, Any] | None = None
    models: list[str] | None = None

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._async_abort_entries_match(
                {CONF_BASE_URL: user_input[CONF_BASE_URL]}
            )
            try:
                self.models = await async_list_models(self.hass, user_input)
            except HomeAssistantError as err:
                LOGGER.error("Connection failed: %s", err)
                errors["base"] = err.translation_key or "unknown"
            except Exception:  # noqa: BLE001
                LOGGER.exception("Unexpected")
                errors["base"] = "unknown"
            else:
                self.data = user_input
                return await self.async_step_model()
        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_model(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick model."""
        assert self.data is not None
        assert self.models is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            model = user_input[CONF_CHAT_MODEL]
            try:
                await async_validate_responses(self.hass, self.data, model)
            except HomeAssistantError as err:
                errors["base"] = err.translation_key or "unknown"
            else:
                return self.async_create_entry(
                    title=self.data[CONF_BASE_URL],
                    data=self.data,
                    subentries=[
                        {
                            "subentry_type": "conversation",
                            "data": {
                                CONF_RECOMMENDED: True,
                                CONF_LLM_HASS_API: [llm.LLM_API_ASSIST],
                                CONF_CHAT_MODEL: model,
                            },
                            "title": model_name_to_title(model),
                            "unique_id": None,
                        },
                    ],
                )
        return self.async_show_form(
            step_id="model",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Optional(CONF_CHAT_MODEL): SelectSelector(
                            SelectSelectorConfig(
                                options=self.models,
                                translation_key=CONF_CHAT_MODEL,
                                mode=SelectSelectorMode.DROPDOWN,
                                custom_value=True,
                            )
                        ),
                    }
                ),
                {CONF_CHAT_MODEL: (user_input or {}).get(CONF_CHAT_MODEL, recommended_model(self.models))},
            ),
            errors=errors,
        )

    @classmethod
    @callback
    @override
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Supported subentries."""
        return {
            "conversation": OpencodeZenConversationFlow,
            "ai_task_data": OpencodeZenTaskFlow,
        }


def _option_schema(hass: HomeAssistant, options: dict[str, Any], models: list[str] | None) -> dict:
    apis: list[SelectOptionDict] = [
        SelectOptionDict(label=api.name, value=api.id) for api in llm.async_get_apis(hass)
    ]
    schema: dict = {
        vol.Optional(CONF_PROMPT, description={"suggested_value": options.get(CONF_PROMPT, llm.DEFAULT_INSTRUCTIONS_PROMPT)}): TemplateSelector(),
        vol.Optional(CONF_LLM_HASS_API): SelectSelector(
            SelectSelectorConfig(options=apis, multiple=True)
        ),
        vol.Optional(
            CONF_CHAT_MODEL,
            description={"suggested_value": options.get(CONF_CHAT_MODEL)},
            default=options.get(CONF_CHAT_MODEL, recommended_model(models)),
        ): SelectSelector(
            SelectSelectorConfig(
                options=models or [],
                translation_key=CONF_CHAT_MODEL,
                mode=SelectSelectorMode.DROPDOWN,
                custom_value=True,
            )
        ),
        vol.Required(CONF_RECOMMENDED, default=options.get(CONF_RECOMMENDED, False)): bool,
        vol.Optional(
            CONF_REQUIRE_CONFIRMATION,
            description={"suggested_value": options.get(CONF_REQUIRE_CONFIRMATION, True)},
            default=options.get(CONF_REQUIRE_CONFIRMATION, True),
        ): bool,
    }
    if options.get(CONF_RECOMMENDED):
        return schema
    schema.update(
        {
            vol.Optional(CONF_MAX_TOKENS, description={"suggested_value": options.get(CONF_MAX_TOKENS)}, default=RECOMMENDED_MAX_TOKENS): int,
            vol.Optional(CONF_TOP_P, description={"suggested_value": options.get(CONF_TOP_P)}, default=RECOMMENDED_TOP_P): NumberSelector(NumberSelectorConfig(min=0, max=1, step=0.05)),
            vol.Optional(CONF_TEMPERATURE, description={"suggested_value": options.get(CONF_TEMPERATURE)}, default=RECOMMENDED_TEMPERATURE): NumberSelector(NumberSelectorConfig(min=0, max=2, step=0.05)),
        }
    )
    return schema


class _BaseSubentryFlow(ConfigSubentryFlow):
    subentry_type: str = "conversation"
    options: dict[str, Any] | None = None
    models: list[str] | None = None
    last_recommended: bool = False

    async def _get_models(self) -> list[str] | None:
        if self.models is None:
            try:
                self.models = await async_list_models(self.hass, self._get_entry().data)
            except HomeAssistantError:
                return None
        return self.models

    async def async_step_user(self, user_input=None) -> SubentryFlowResult:
        if self._get_entry().state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="entry_not_loaded")
        models = await self._get_models()
        if models is None:
            return self.async_abort(reason="cannot_connect")
        self.options = {
            CONF_RECOMMENDED: True,
            CONF_LLM_HASS_API: [llm.LLM_API_ASSIST],
            CONF_CHAT_MODEL: recommended_model(models),
        }
        self.last_recommended = True
        return await self.async_step_init()

    async def async_step_reconfigure(self, user_input=None) -> SubentryFlowResult:
        return await self.async_step_init()

    async def async_step_init(self, user_input=None) -> SubentryFlowResult:
        if self._get_entry().state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="entry_not_loaded")
        if self.options is None:
            self.options = self._get_reconfigure_subentry().data.copy()
            self.last_recommended = bool(self.options.get(CONF_RECOMMENDED, False))
        models = await self._get_models()
        if models is None:
            return self.async_abort(reason="cannot_connect")
        options = self.options
        if user_input is not None:
            try:
                await async_validate_responses(
                    self.hass, self._get_entry().data, user_input[CONF_CHAT_MODEL]
                )
            except HomeAssistantError as err:
                return self.async_show_form(
                    step_id="init",
                    data_schema=self.add_suggested_values_to_schema(
                        vol.Schema(_option_schema(self.hass, options, models)), user_input
                    ),
                    errors={"base": err.translation_key or "unknown"},
                )
            if user_input[CONF_RECOMMENDED] == self.last_recommended:
                title = model_name_to_title(user_input[CONF_CHAT_MODEL])
                if self.source == "user":
                    return self.async_create_entry(title=title, data=user_input)
                return self.async_update_and_abort(
                    self._get_entry(), self._get_reconfigure_subentry(),
                    data=user_input, title=title,
                )
            self.last_recommended = user_input[CONF_RECOMMENDED]
            options = {
                CONF_RECOMMENDED: user_input[CONF_RECOMMENDED],
                CONF_PROMPT: user_input.get(CONF_PROMPT),
                CONF_CHAT_MODEL: user_input[CONF_CHAT_MODEL],
                CONF_LLM_HASS_API: user_input.get(CONF_LLM_HASS_API, []),
                CONF_REQUIRE_CONFIRMATION: user_input.get(CONF_REQUIRE_CONFIRMATION, True),
            }
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(_option_schema(self.hass, options, models)), options
            ),
        )


class OpencodeZenConversationFlow(_BaseSubentryFlow):
    """Conversation subentry."""

    subentry_type = "conversation"


class OpencodeZenTaskFlow(_BaseSubentryFlow):
    """AI task subentry."""

    subentry_type = "ai_task_data"
