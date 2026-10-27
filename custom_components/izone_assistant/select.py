"""Zone mode select per zone, and the controller's Control mode select."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import (
    IZoneDerivedEntity,
    controller_object_prefix,
    resolve_entry,
    zone_object_prefix,
)
from .zone_control import CONTROL_MODES, ZoneControl, zone_mode, zone_supports_climate


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    control: ZoneControl = entry.runtime_data
    resolved = resolve_entry(hass, entry)
    entities: list[SelectEntity] = [
        ZoneModeSelect(
            hass, eid, uid, "zone_mode", control=control,
            object_prefix=zone_object_prefix(hass, eid),
        )
        for eid, uid in resolved.zones
    ]
    if resolved.controller:
        ceid, cuid = resolved.controller
        entities.append(
            ControlModeSelect(
                hass, ceid, cuid, "control_mode", control.all_zones, control=control,
                object_prefix=controller_object_prefix(hass, cuid),
            )
        )
    async_add_entities(entities)


class ZoneModeSelect(IZoneDerivedEntity, SelectEntity):
    """Closed / Open / Climate for one zone (Closed / Open for zones without a sensor).

    Changes only that zone. The safety zone won't close if it's the last open zone.
    """

    _entity_domain = "select"

    def __init__(self, hass, source_entity_id, unique_prefix, key, *, control: ZoneControl, **kwargs) -> None:
        super().__init__(hass, source_entity_id, unique_prefix, key, **kwargs)
        self._control = control
        self._attr_options = (
            ["closed", "open", "climate"]
            if zone_supports_climate(hass, source_entity_id)
            else ["closed", "open"]
        )

    @property
    def current_option(self) -> str | None:
        mode = zone_mode(self.src)
        return mode if mode in self.options else None

    async def async_select_option(self, option: str) -> None:
        await self._control.async_select_zone(self._source, option)


class ControlModeSelect(IZoneDerivedEntity, SelectEntity):
    """Local / Master / Hybrid / Closed for every zone on the controller."""

    _entity_domain = "select"
    _attr_options = CONTROL_MODES

    def __init__(self, hass, source_entity_id, unique_prefix, key, zone_eids, *, control: ZoneControl, **kwargs) -> None:
        super().__init__(hass, source_entity_id, unique_prefix, key, zone_eids, **kwargs)
        self._control = control

    @property
    def available(self) -> bool:
        return super().available and bool(self._control.zones)

    @property
    def current_option(self) -> str | None:
        return self._control.current_control_mode()

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        return {
            "safety_zone": self._control.safety_zone(),
            "constant_zone": self._control.constant_zone,
        }

    async def async_select_option(self, option: str) -> None:
        await self._control.async_apply_control_mode(option)
