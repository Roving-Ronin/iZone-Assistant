"""Per-zone airflow min/max (izone.airflow_min / airflow_max) and the controller's Set temperature."""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import AIRFLOW_CEILING, AIRFLOW_FLOOR, AIRFLOW_STEP
from .entity import (
    IZoneDerivedEntity,
    as_number,
    controller_object_prefix,
    resolve_entry,
    zone_object_prefix,
)
from .zone_control import ZoneControl


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    resolved = resolve_entry(hass, entry)
    entities: list[NumberEntity] = [
        AirflowNumber(
            hass, eid, uid, kind,
            limits=resolved.airflow_limits[eid],
            object_prefix=zone_object_prefix(hass, eid),
        )
        for eid, uid in resolved.zones
        for kind in ("min", "max")
    ]
    if resolved.controller:
        ceid, cuid = resolved.controller
        control: ZoneControl = entry.runtime_data
        entities.append(
            SetTemperatureNumber(
                hass, ceid, cuid, "set_temperature", control.all_zones, control=control,
                object_prefix=controller_object_prefix(hass, cuid),
            )
        )
    async_add_entities(entities)


class AirflowNumber(IZoneDerivedEntity, NumberEntity):
    _attr_native_step = AIRFLOW_STEP
    _attr_native_unit_of_measurement = PERCENTAGE
    _entity_domain = "number"

    def __init__(
        self, hass, source_entity_id, source_unique_id, kind: str,
        *, limits: tuple[int, int] = (AIRFLOW_FLOOR, AIRFLOW_CEILING), **kwargs,
    ) -> None:
        super().__init__(hass, source_entity_id, source_unique_id, f"airflow_{kind}", **kwargs)
        self._kind = kind
        self._floor, self._ceiling = limits

    def _limit(self, which: str, fallback: float) -> float:
        value = as_number(self.src_attr(f"airflow_{which}"))
        return fallback if value is None else value

    @property
    def native_value(self) -> float | None:
        return as_number(self.src_attr(f"airflow_{self._kind}"))

    @property
    def available(self) -> bool:
        return super().available and self.native_value is not None

    @property
    def extra_state_attributes(self) -> dict[str, int]:
        return {"floor": self._floor, "ceiling": self._ceiling}

    @property
    def native_min_value(self) -> float:
        if self._kind == "max":  # max can't go below the current min
            return max(self._floor, self._limit("min", self._floor))
        return self._floor

    @property
    def native_max_value(self) -> float:
        if self._kind == "min":  # min can't exceed the current max
            return min(self._ceiling, self._limit("max", self._ceiling))
        return self._ceiling

    async def async_set_native_value(self, value: float) -> None:
        await self.hass.services.async_call(
            "izone",
            f"airflow_{self._kind}",
            {"airflow": int(value)},
            target={"entity_id": self._source},
            blocking=True,
        )


class SetTemperatureNumber(IZoneDerivedEntity, NumberEntity):
    """The unit's target, set from one place.

    While a zone is in control and in Climate (Local / Hybrid), the unit runs to
    that zone's target, and a unit setpoint sent to the controller is overwritten
    on the next refresh, so this writes to the control zone. Otherwise (Master /
    Closed) it writes to the controller's own setpoint.
    """

    _entity_domain = "number"
    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_step = 0.5

    def __init__(self, hass, source_entity_id, unique_prefix, key, zone_eids, *, control: ZoneControl, **kwargs) -> None:
        super().__init__(hass, source_entity_id, unique_prefix, key, zone_eids, **kwargs)
        self._control = control

    def _target_entity(self) -> str:
        return self._control.setpoint_zone() or self._source

    @property
    def native_value(self) -> float | None:
        if (zone := self._control.setpoint_zone()) is not None:
            state = self.hass.states.get(zone)
            return as_number(state.attributes.get("temperature")) if state else None
        return as_number(self.src_attr("temp_setpoint"))

    @property
    def available(self) -> bool:
        return super().available and self.native_value is not None

    @property
    def native_min_value(self) -> float:
        return as_number(self.src_attr("min_temp")) or 15.0

    @property
    def native_max_value(self) -> float:
        return as_number(self.src_attr("max_temp")) or 30.0

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        return {"applies_to": self._target_entity()}

    async def async_set_native_value(self, value: float) -> None:
        await self.hass.services.async_call(
            "climate", "set_temperature",
            {"entity_id": self._target_entity(), "temperature": value},
            blocking=True,
        )
