"""Per-zone airflow min/max, set via izone.airflow_min / izone.airflow_max."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import AIRFLOW_CEILING, AIRFLOW_FLOOR, AIRFLOW_STEP
from .entity import IZoneDerivedEntity, as_number, resolve_entry, zone_object_prefix


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    resolved = resolve_entry(hass, entry)
    async_add_entities(
        AirflowNumber(
            hass, eid, uid, kind,
            limits=resolved.airflow_limits[eid],
            object_prefix=zone_object_prefix(hass, eid),
        )
        for eid, uid in resolved.zones
        for kind in ("min", "max")
    )


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
