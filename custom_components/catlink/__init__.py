"""The component."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_DEVICES, CONF_PASSWORD, CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.update_coordinator import UpdateFailed

from .const import (
    _LOGGER,
    CONF_ACCOUNTS,
    CONF_DEVICE_IDS,
    DOMAIN,
    SUPPORTED_DOMAINS,
)
from .modules.account import Account
from .modules.devices_coordinator import DevicesCoordinator

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, hass_config: dict) -> bool:
    """Set up the CatLink component."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault(CONF_ACCOUNTS, {})
    hass.data[DOMAIN].setdefault(CONF_DEVICES, {})
    hass.data[DOMAIN].setdefault("coordinators", {})
    hass.data[DOMAIN].setdefault("add_entities", {})
    hass.data[DOMAIN].setdefault("config", {})
    hass.data[DOMAIN].setdefault("entry_coordinators", {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up CatLink from a config entry."""
    hass.data[DOMAIN].setdefault("config", {})
    hass.data[DOMAIN]["config"].setdefault(CONF_DEVICES, [])

    config = {**entry.data, **(entry.options or {})}
    acc = Account(hass, config)
    device_ids = entry.options.get(CONF_DEVICE_IDS) if entry.options else None
    coordinator = DevicesCoordinator(acc, entry.entry_id, device_ids=device_ids)

    try:
        await acc.async_check_auth()
    except UpdateFailed as exc:
        raise ConfigEntryNotReady(str(exc)) from None
    if entry.data.get(CONF_PASSWORD) and CONF_TOKEN in entry.data:
        data = dict(entry.data)
        data.pop(CONF_TOKEN)
        hass.config_entries.async_update_entry(entry, data=data)
    await coordinator.async_refresh()

    hass.data[DOMAIN][CONF_ACCOUNTS][acc.uid] = acc
    hass.data[DOMAIN]["coordinators"][coordinator.name] = coordinator
    hass.data[DOMAIN]["entry_coordinators"][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, SUPPORTED_DOMAINS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    await hass.config_entries.async_unload_platforms(entry, SUPPORTED_DOMAINS)

    uid = f"{entry.data.get('phone_iac', '86')}-{entry.data.get('phone', '')}"
    if uid in hass.data[DOMAIN][CONF_ACCOUNTS]:
        del hass.data[DOMAIN][CONF_ACCOUNTS][uid]
    coordinator = hass.data[DOMAIN]["entry_coordinators"].pop(entry.entry_id, None)
    if coordinator is not None:
        hass.data[DOMAIN]["coordinators"].pop(coordinator.name, None)
    if entry.entry_id in hass.data[DOMAIN].get("add_entities", {}):
        del hass.data[DOMAIN]["add_entities"][entry.entry_id]

    return True
