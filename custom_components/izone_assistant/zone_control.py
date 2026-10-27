"""Zone mode control: per-zone modes, the controller's Control mode, and the safety zone.

Zone modes map onto core iZone's zone climate entities:
    closed -> hvac_mode off, open -> fan_only, climate -> heat_cool

Control mode (controller select):
    local  - zones with a sensor -> Climate, zones without one -> Open (iZone zones mode)
    master - every zone -> Open (the wall controller / return air sensor drives the unit)
    hybrid - every zone -> the last mode it was given individually
    closed - every zone -> Closed, except the safety zone

Safety zone, so the ducting always has an open zone, whether the unit is on or off:
    the constant zone if there is one and it's Open, otherwise the controller's
    current control zone.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.helpers.storage import Store

from .const import CLIMATE_STATES, DOMAIN, ZONE_MODE_MAP

_LOGGER = logging.getLogger(__name__)

MODE_TO_HVAC = {"closed": "off", "open": "fan_only", "climate": "heat_cool"}
CONTROL_MODES = ["local", "master", "hybrid", "closed"]
OPEN_MODES = {"open", "climate"}
EXPECTED_TIMEOUT = 120  # seconds to wait for a bulk change to be reported back

STORAGE_VERSION = 1


def zone_mode(state: State | None) -> str | None:
    return None if state is None else ZONE_MODE_MAP.get(state.state)


def zone_supports_climate(hass: HomeAssistant, zone_entity_id: str) -> bool:
    """True if iZone has a temperature sensor assigned to the zone.

    Core's iZone integration offers Climate (heat_cool) only for zones with a
    sensor. hvac_modes lists the modes the zone *supports*, so it doesn't change
    when the zone is set to Open or Closed. If the zone's state isn't available
    yet, assume it has a sensor.
    """
    state = hass.states.get(zone_entity_id)
    if state is None or "hvac_modes" not in state.attributes:
        return True
    return any(m in CLIMATE_STATES for m in state.attributes["hvac_modes"])


def detect_constant_zone(hass: HomeAssistant, zone_entity_ids: list[str]) -> str | None:
    """The zone iZone names 'Constant Zone', if any."""
    for eid in zone_entity_ids:
        state = hass.states.get(eid)
        if state is not None and "constant" in state.name.casefold():
            return eid
    return None


class ZoneControl:
    """Zone modes for one config entry: individual changes, bulk changes and safety."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        controller: str | None,
        zones: list[str],
        all_zones: list[str],
        constant_zone: str | None,
    ) -> None:
        self.hass = hass
        self.controller = controller        # controller climate entity_id
        self.zones = zones                  # selected zone climate entity_ids
        self.all_zones = all_zones          # every zone on the controller (for safety)
        self.constant_zone = constant_zone  # constant zone entity_id, or None
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}")
        self._uids = {
            eid: (e.unique_id if (e := er.async_get(hass).async_get(eid)) else eid)
            for eid in all_zones
        }
        self.remembered: dict[str, str] = {}  # zone unique_id -> last individually set mode
        self._expected: dict[str, str] = {}   # zone entity_id -> mode a bulk change is waiting for
        self._unsub: list = []

    # ---------------------------------------------------------------- lifecycle

    async def async_start(self) -> None:
        data = await self._store.async_load() or {}
        self.remembered = dict(data.get("remembered", {}))
        # Before anything has been recorded, a zone's current mode is its remembered mode
        changed = False
        for eid in self.zones:
            uid = self._uids.get(eid, eid)
            if uid not in self.remembered and (mode := self.mode_of(eid)) is not None:
                self.remembered[uid] = mode
                changed = True
        if changed:
            self._save()
        self._unsub.append(
            async_track_state_change_event(self.hass, self.all_zones, self._on_zone_change)
        )

    @callback
    def async_stop(self) -> None:
        for unsub in self._unsub:
            unsub()
        self._unsub.clear()

    def _save(self) -> None:
        # Zone changes are infrequent: save straight away so a restart never loses one
        self.hass.async_create_task(
            self._store.async_save({"remembered": dict(self.remembered)}),
            "izone_assistant save remembered zone modes",
        )

    @callback
    def _on_zone_change(self, event: Event[EventStateChangedData]) -> None:
        """Record individual changes (wall panel, tablet, a zone's own select) for Hybrid."""
        eid = event.data["entity_id"]
        mode = zone_mode(event.data["new_state"])
        if mode is None or eid not in self.zones:
            return
        if (expected := self._expected.pop(eid, None)) is not None and expected == mode:
            return  # a bulk change arriving, not an individual one
        uid = self._uids.get(eid, eid)
        if self.remembered.get(uid) != mode:
            self.remembered[uid] = mode
            self._save()

    # ---------------------------------------------------------------- state

    def mode_of(self, eid: str) -> str | None:
        return zone_mode(self.hass.states.get(eid))

    def safety_zone(self) -> str | None:
        """The constant zone if it's Open, otherwise the controller's current control zone."""
        if self.constant_zone and self.mode_of(self.constant_zone) == "open":
            return self.constant_zone
        if self.controller and (ctrl := self.hass.states.get(self.controller)):
            idx = ctrl.attributes.get("control_zone")
            for eid in self.all_zones:
                state = self.hass.states.get(eid)
                if state is not None and idx is not None and state.attributes.get("zone_index") == idx:
                    return eid
        return None

    def _any_open(self, modes: dict[str, str | None]) -> bool:
        return any(m in OPEN_MODES for m in modes.values())

    def current_control_mode(self) -> str | None:
        modes = {eid: self.mode_of(eid) for eid in self.zones}
        if not modes or any(m is None for m in modes.values()):
            return None
        safety = self.safety_zone()
        if any(m == "closed" for m in modes.values()) and all(
            m == "closed" or (eid == safety and m == "open") for eid, m in modes.items()
        ):
            return "closed"
        sensored = {eid: zone_supports_climate(self.hass, eid) for eid in modes}
        if any(sensored.values()) and all(
            m == ("climate" if sensored[eid] else "open") for eid, m in modes.items()
        ):
            return "local"
        if all(m == "open" for m in modes.values()):
            return "master"
        return "hybrid"

    # ---------------------------------------------------------------- changes

    async def _async_set(self, eid: str, mode: str, *, bulk: bool) -> None:
        if self.mode_of(eid) == mode:
            return
        if bulk:
            self._expected[eid] = mode
            async_call_later(self.hass, EXPECTED_TIMEOUT, lambda _now, e=eid: self._expected.pop(e, None))
        await self.hass.services.async_call(
            "climate", "set_hvac_mode",
            {"entity_id": eid, "hvac_mode": MODE_TO_HVAC[mode]},
            blocking=True,
        )

    async def async_select_zone(self, eid: str, mode: str) -> None:
        """A zone's own select: changes only that zone, keeping the safety zone open."""
        if mode == "closed":
            others = {z: self.mode_of(z) for z in self.all_zones if z != eid}
            if not self._any_open(others):
                safety = self.safety_zone()
                if safety is None or safety == eid:
                    name = (s.name if (s := self.hass.states.get(eid)) else eid)
                    raise HomeAssistantError(
                        translation_domain=DOMAIN,
                        translation_key="safety_zone_must_stay_open",
                        translation_placeholders={"zone": name},
                    )
                await self._async_set(eid, mode, bulk=False)
                await self._async_set(safety, "open", bulk=True)
                return
        await self._async_set(eid, mode, bulk=False)

    async def async_apply_control_mode(self, control_mode: str) -> None:
        """The controller's Control mode select: sets every zone."""
        safety = self.safety_zone()  # decided before anything changes
        targets: dict[str, str] = {}
        for eid in self.zones:
            sensored = zone_supports_climate(self.hass, eid)
            if control_mode == "local":
                targets[eid] = "climate" if sensored else "open"
            elif control_mode == "master":
                targets[eid] = "open"
            elif control_mode == "closed":
                targets[eid] = "closed"
            elif control_mode == "hybrid":
                mode = self.remembered.get(self._uids.get(eid, eid)) or self.mode_of(eid) or "open"
                targets[eid] = mode if (mode != "climate" or sensored) else "open"

        if control_mode in ("closed", "hybrid"):
            result = {z: targets.get(z, self.mode_of(z)) for z in self.all_zones}
            if not self._any_open(result):
                if safety is None:
                    raise HomeAssistantError(
                        translation_domain=DOMAIN, translation_key="no_safety_zone"
                    )
                targets[safety] = "open"

        for eid, mode in targets.items():
            await self._async_set(eid, mode, bulk=True)
