"""Base entity: derives its values from an existing entity (iZone climate, or the outdoor source)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device import async_entity_id_to_device
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.event import async_track_state_change_event

from . import get_zone_ids
from homeassistant.util import slugify

from .const import (
    AIRFLOW_CEILING,
    AIRFLOW_FLOOR,
    CONF_AIRFLOW_LIMITS,
    CONF_CONTROLLER,
    CONF_OUTDOOR,
    OBJECT_PREFIX,
    OBJECT_SUFFIX,
    ZONE_MODE_MAP,
)


@dataclass
class Resolved:
    """Current entity_ids for a config entry (stored as registry ids)."""

    controller: tuple[str, str] | None          # (entity_id, unique_id)
    zones: list[tuple[str, str]] = field(default_factory=list)
    outdoor: str | None = None                  # entity_id
    airflow_limits: dict[str, tuple[int, int]] = field(default_factory=dict)  # entity_id -> (floor, ceiling)


def _entity_id(hass: HomeAssistant, stored: str | None) -> str | None:
    if not stored:
        return None
    try:
        return er.async_validate_entity_id(er.async_get(hass), stored)
    except vol.Invalid:
        return None


def _with_uid(hass: HomeAssistant, stored: str) -> tuple[str, str] | None:
    if not (entity_id := _entity_id(hass, stored)):
        return None
    entry = er.async_get(hass).async_get(entity_id)
    return (entity_id, entry.unique_id) if entry else None


def resolve_entry(hass: HomeAssistant, entry: ConfigEntry) -> Resolved:
    stored_limits = entry.options.get(CONF_AIRFLOW_LIMITS, {})
    resolved = Resolved(
        controller=_with_uid(hass, entry.data[CONF_CONTROLLER]),
        outdoor=_entity_id(
            hass, entry.options.get(CONF_OUTDOOR, entry.data.get(CONF_OUTDOOR))
        ),
    )
    for rid in get_zone_ids(entry):
        if not (zone := _with_uid(hass, rid)):
            continue
        resolved.zones.append(zone)
        floor, ceiling = stored_limits.get(rid, (AIRFLOW_FLOOR, AIRFLOW_CEILING))
        resolved.airflow_limits[zone[0]] = (int(floor), int(ceiling))
    return resolved


def zone_object_prefix(hass: HomeAssistant, zone_entity_id: str) -> str:
    """izone_<zone name>, using the name entered on the iZone controller."""
    state = hass.states.get(zone_entity_id)
    name = slugify(state.name) if state is not None else ""
    return f"{OBJECT_PREFIX}_{name or zone_entity_id.split('.', 1)[1]}"


def controller_object_prefix(hass: HomeAssistant, controller_uid: str) -> str:
    """izone_controller, or izone_controller_<serial> when more than one iZone controller exists."""
    controllers = [
        e
        for e in er.async_get(hass).entities.values()
        if e.platform == "izone" and e.domain == "climate" and "_z" not in (e.unique_id or "")
    ]
    base = f"{OBJECT_PREFIX}_controller"
    return base if len(controllers) <= 1 else f"{base}_{controller_uid}"


def controller_zone_entity_ids(hass: HomeAssistant, controller_uid: str) -> list[str]:
    """Every zone climate entity iZone created for this controller (unique_id <uid>_z<n>)."""
    prefix = f"{controller_uid}_z"
    return [
        e.entity_id
        for e in er.async_get(hass).entities.values()
        if e.platform == "izone" and e.domain == "climate" and (e.unique_id or "").startswith(prefix)
    ]


def as_number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def zone_mode(state: State | None) -> str | None:
    return None if state is None else ZONE_MODE_MAP.get(state.state)


class IZoneDerivedEntity(Entity):
    """Tracks a source entity (plus optional extras) and re-renders on change."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _entity_domain = "sensor"

    def __init__(
        self,
        hass: HomeAssistant,
        source_entity_id: str,
        unique_prefix: str,
        key: str,
        extra_sources: list[str] | None = None,
        device_entity_id: str | None = None,
        *,
        object_prefix: str,
    ) -> None:
        self._source = source_entity_id
        self._tracked = [source_entity_id, *(extra_sources or [])]
        self._attr_translation_key = key
        self._attr_unique_id = f"{unique_prefix}_{key}"
        # Suggested entity_id, applied only when the entity is first created.
        # Display names stay device-based ("Study Temperature").
        self.entity_id = f"{self._entity_domain}.{object_prefix}_{OBJECT_SUFFIX[key]}"
        # Show under the existing iZone controller / zone device (and so its area),
        # the way core helpers do: set device_entry rather than device_info, which
        # would try to add this config entry to iZone's device.
        self.device_entry = async_entity_id_to_device(
            hass, device_entity_id or source_entity_id
        )

    @property
    def src(self) -> State | None:
        return self.hass.states.get(self._source)

    def src_attr(self, name: str) -> Any:
        state = self.src
        return None if state is None else state.attributes.get(name)

    @property
    def available(self) -> bool:
        state = self.src
        return state is not None and state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_state_change_event(self.hass, self._tracked, self._on_change)
        )

    @callback
    def _on_change(self, event: Event[EventStateChangedData]) -> None:
        self.async_write_ha_state()
