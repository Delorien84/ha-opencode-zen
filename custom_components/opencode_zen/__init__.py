"""The OpenCode Zen integration."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady, HomeAssistantError

from .api import async_list_models

PLATFORMS = (Platform.CONVERSATION, Platform.AI_TASK)

type OpencodeZenConfigEntry = ConfigEntry[dict]


async def async_setup_entry(hass: HomeAssistant, entry: OpencodeZenConfigEntry) -> bool:
    """Set up OpenCode Zen from a config entry."""
    try:
        await async_list_models(hass, entry.data)
    except HomeAssistantError as err:
        if err.translation_key == "invalid_auth":
            raise ConfigEntryAuthFailed(
                translation_domain=err.translation_domain,
                translation_key=err.translation_key,
                translation_placeholders=err.translation_placeholders,
            ) from err
        raise ConfigEntryNotReady(
            translation_domain=err.translation_domain,
            translation_key=err.translation_key,
            translation_placeholders=err.translation_placeholders,
        ) from err

    entry.runtime_data = dict(entry.data)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_update_options))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: OpencodeZenConfigEntry) -> bool:
    """Unload OpenCode Zen."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_update_options(hass: HomeAssistant, entry: OpencodeZenConfigEntry) -> None:
    """Reload on options change."""
    await hass.config_entries.async_reload(entry.entry_id)
