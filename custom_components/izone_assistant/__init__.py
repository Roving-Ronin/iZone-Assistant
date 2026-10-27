"""iZone Assistant: derived sensors and airflow controls for the core iZone integration."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import CONF_CONSTANT_ZONE, CONF_CONTROLLER, CONF_CONTROLLER_UID, CONF_ZONES, NO_CONSTANT_ZONE

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.NUMBER, Platform.SELECT]


def get_zone_ids(entry: ConfigEntry) -> list[str]:
    """Zones selected in options, falling back to the initial setup."""
    return entry.options.get(CONF_ZONES, entry.data[CONF_ZONES])


def _entity_id(hass: HomeAssistant, stored: str | None) -> str | None:
    if not stored:
        return None
    try:
        return er.async_validate_entity_id(er.async_get(hass), stored)
    except vol.Invalid:
        return None


def resolve_constant_zone(hass: HomeAssistant, entry: ConfigEntry, all_zones: list[str]) -> str | None:
    """The constant zone: Configure's choice if made, otherwise the zone iZone names 'Constant Zone'."""
    from .zone_control import detect_constant_zone

    stored = entry.options.get(CONF_CONSTANT_ZONE)
    if stored == NO_CONSTANT_ZONE:
        return None
    if stored and (eid := _entity_id(hass, stored)):
        return eid
    return detect_constant_zone(hass, all_zones)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up from a config entry."""
    from .entity import controller_zone_entity_ids
    from .zone_control import ZoneControl

    all_zones = controller_zone_entity_ids(hass, entry.data[CONF_CONTROLLER_UID])
    zones = [eid for rid in get_zone_ids(entry) if (eid := _entity_id(hass, rid))]
    control = ZoneControl(
        hass,
        entry.entry_id,
        controller=_entity_id(hass, entry.data[CONF_CONTROLLER]),
        zones=zones,
        all_zones=all_zones,
        constant_zone=resolve_constant_zone(hass, entry, all_zones),
    )
    await control.async_start()
    entry.runtime_data = control
    entry.async_on_unload(control.async_stop)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload when the zone selection changes."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
