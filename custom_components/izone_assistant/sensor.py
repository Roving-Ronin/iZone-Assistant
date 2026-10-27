"""Derived iZone sensors."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT, EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CLIMATE_STATES, FAN_MODES, HVAC_MODES, ZONE_MODES
from .entity import (
    IZoneDerivedEntity,
    as_number,
    controller_object_prefix,
    controller_zone_entity_ids,
    resolve_entry,
    zone_mode,
    zone_object_prefix,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    resolved = resolve_entry(hass, entry)
    entities: list[SensorEntity] = []

    for eid, uid in resolved.zones:
        zp = zone_object_prefix(hass, eid)
        sensored = zone_has_sensor(hass, eid)
        entities += [
            ZoneTemperatureSensor(
                hass, eid, uid, "zone_temperature", has_sensor=sensored, object_prefix=zp
            ),
            ZoneModeSensor(hass, eid, uid, "zone_mode", object_prefix=zp),
        ]
        if sensored:  # constant and open/close zones have no setpoint
            entities.append(
                ZoneTargetSensor(hass, eid, uid, "zone_target_temperature", object_prefix=zp)
            )

    if resolved.controller:
        ceid, cuid = resolved.controller
        cp = controller_object_prefix(hass, cuid)
        zone_eids = controller_zone_entity_ids(hass, cuid)  # all zones, for name matching / count
        entities += [
            HvacModeSensor(hass, ceid, cuid, "hvac_mode", object_prefix=cp),
            FanModeSensor(hass, ceid, cuid, "fan_mode", object_prefix=cp),
            ControllerTargetSensor(
                hass, ceid, cuid, "controller_target_temperature", object_prefix=cp
            ),
            ControllerAttrTempSensor(
                hass, ceid, cuid, "min_set_temperature", attr="min_temp", object_prefix=cp
            ),
            ControllerAttrTempSensor(
                hass, ceid, cuid, "max_set_temperature", attr="max_temp", object_prefix=cp
            ),
            ControlZoneSensor(hass, ceid, cuid, "control_zone", zone_eids, object_prefix=cp),
        ]
        if resolved.outdoor:
            # Lives on the controller device; its value comes from the chosen source
            entities.append(
                OutdoorTemperatureSensor(
                    hass, resolved.outdoor, cuid, "outdoor_temperature",
                    device_entity_id=ceid, object_prefix=cp,
                )
            )

    async_add_entities(entities)

    # Remove sensors this entry no longer creates (e.g. Target temperature on a
    # constant zone, created by an earlier version)
    ent_reg = er.async_get(hass)
    keep = {e.unique_id for e in entities}
    for reg_entry in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        if reg_entry.domain == "sensor" and reg_entry.unique_id not in keep:
            ent_reg.async_remove(reg_entry.entity_id)


def zone_has_sensor(hass: HomeAssistant, zone_entity_id: str) -> bool:
    """True if iZone has a temperature sensor assigned to the zone.

    Core's iZone integration offers Climate (heat_cool) only for zones of type
    'auto', which are the zones with a sensor. hvac_modes lists the modes the
    zone *supports*, so it doesn't change when the zone is set to Open or Closed.
    If the zone's state isn't available yet, assume it has a sensor.
    """
    state = hass.states.get(zone_entity_id)
    if state is None or "hvac_modes" not in state.attributes:
        return True
    return any(m in CLIMATE_STATES for m in state.attributes["hvac_modes"])


# ---------------------------------------------------------------- temperatures

class _TempSensor(IZoneDerivedEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_suggested_display_precision = 1

    @property
    def available(self) -> bool:
        return super().available and self.native_value is not None


class ZoneTemperatureSensor(_TempSensor):
    """Room temperature, with zone_mode attribute (kept for existing dashboards).

    Zones without a sensor (constant, open/close) get this entity disabled by
    default; if someone enables it, it reports 0 while the zone has no reading,
    rather than unavailable.
    """

    def __init__(self, hass, source_entity_id, unique_prefix, key, *, has_sensor: bool = True, **kwargs):
        super().__init__(hass, source_entity_id, unique_prefix, key, **kwargs)
        self._has_sensor = has_sensor
        if not has_sensor:
            self._attr_entity_registry_enabled_default = False
            # The 0 fallback isn't a measurement: keep it out of long-term statistics
            self._attr_state_class = None

    @property
    def native_value(self) -> float | None:
        value = as_number(self.src_attr("current_temperature"))
        if value is None and not self._has_sensor:
            return 0.0
        return value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        mode = zone_mode(self.src)
        return {"zone_mode": mode.title() if mode else None, "has_sensor": self._has_sensor}


class ZoneTargetSensor(_TempSensor):
    """Zone setpoint; only available in Climate mode."""

    @property
    def native_value(self) -> float | None:
        return as_number(self.src_attr("temperature"))

    @property
    def available(self) -> bool:
        state = self.src
        return super().available and state is not None and state.state in CLIMATE_STATES


class ControllerTargetSensor(_TempSensor):
    """Control zone setpoint in zone-control mode, else the unit setpoint.

    Core's controller reports control_zone_setpoint = None when the unit
    setpoint is in use, so no hard-coded zone number (13/15) is needed.
    """

    @property
    def native_value(self) -> float | None:
        czs = as_number(self.src_attr("control_zone_setpoint"))
        return czs if czs is not None else as_number(self.src_attr("temp_setpoint"))


class ControllerAttrTempSensor(_TempSensor):
    """A temperature read straight from a controller attribute (min_temp / max_temp)."""

    # Static controller limits that duplicate climate.izone_controller's
    # min_temp / max_temp attributes: diagnostic and disabled by default.
    _attr_state_class = None
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, hass, source_entity_id, unique_prefix, key, *, attr: str, **kwargs) -> None:
        super().__init__(hass, source_entity_id, unique_prefix, key, **kwargs)
        self._source_attr = attr

    @property
    def native_value(self) -> float | None:
        return as_number(self.src_attr(self._source_attr))


class OutdoorTemperatureSensor(_TempSensor):
    """Outdoor temperature from a chosen sensor (BoM, Open-Meteo, local station) or weather entity."""

    @property
    def native_value(self) -> float | None:
        state = self.src
        if state is None:
            return None
        if state.domain == "weather":
            return as_number(state.attributes.get("temperature"))
        return as_number(state.state)

    @property
    def native_unit_of_measurement(self) -> str:
        # Report in the source's unit; HA converts to the user's unit system
        state = self.src
        if state is not None:
            unit = (
                state.attributes.get("temperature_unit")
                if state.domain == "weather"
                else state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
            )
            if unit in (UnitOfTemperature.CELSIUS, UnitOfTemperature.FAHRENHEIT):
                return unit
        return UnitOfTemperature.CELSIUS

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"source": self._source}


# ---------------------------------------------------------------- modes

class _EnumSensor(IZoneDerivedEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.ENUM

    def _value(self) -> str | None:
        raise NotImplementedError

    @property
    def native_value(self) -> str | None:
        value = self._value()
        return value if value in (self._attr_options or []) else None


class ZoneModeSensor(_EnumSensor):
    """closed / open / climate."""

    _attr_options = ZONE_MODES

    def _value(self) -> str | None:
        return zone_mode(self.src)


class HvacModeSensor(_EnumSensor):
    """Unit mode: off / heat / cool / heat_cool / dry / fan_only (raw values, translated in the UI).

    Duplicates the climate.izone_controller state, so disabled by default;
    enable it for a clean mode timeline in history.
    """

    _attr_options = HVAC_MODES
    _attr_entity_registry_enabled_default = False

    def _value(self) -> str | None:
        state = self.src
        return None if state is None else state.state


class FanModeSensor(_EnumSensor):
    """Unit fan: low / medium / high / top / auto. Duplicates the fan_mode attribute; disabled by default."""

    _attr_options = FAN_MODES
    _attr_entity_registry_enabled_default = False

    def _value(self) -> str | None:
        return self.src_attr("fan_mode")


class ControlZoneSensor(IZoneDerivedEntity, SensorEntity):
    """Name of the control zone, matched via each zone's zone_index attribute.

    control_zone and zone_index are both 0-based (the bridge's zone number is
    index + 1). Matching uses all of the controller's zones, not just the ones
    selected in options, so an unselected zone is still named.
    """

    def __init__(self, hass, source_entity_id, unique_prefix, key, zone_eids, **kwargs):
        super().__init__(hass, source_entity_id, unique_prefix, key, zone_eids, **kwargs)
        self._zone_eids = zone_eids

    @property
    def native_value(self) -> str | None:
        idx = as_number(self.src_attr("control_zone"))
        if idx is None:
            return None
        idx = int(idx)
        for eid in self._zone_eids:
            zone = self.hass.states.get(eid)
            if zone is not None and zone.attributes.get("zone_index") == idx:
                return zone.name
        # Beyond the controller's zones (e.g. 13 / 15): the unit setpoint is in control.
        # Fall back to core's own rule of thumb (13+) if the zone count is unknown.
        zone_count = len(self._zone_eids)
        if idx >= (zone_count if zone_count else 13):
            return "Unit setpoint"
        return f"Zone {idx + 1}"  # in range but no entity: panel (1-based) number

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"control_zone_index": self.src_attr("control_zone")}
