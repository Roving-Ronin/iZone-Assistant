"""Config flow for iZone Assistant.

No zone count or names are asked for: the controller and its zones are
discovered from the entity registry (iZone zone unique_ids are
"<controller_uid>_z<n>"), and names come from the existing zone entities.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
)

from .const import (
    AIRFLOW_CEILING,
    AIRFLOW_FLOOR,
    AIRFLOW_STEP,
    CONF_AIRFLOW_LIMITS,
    CONF_CONTROLLER,
    CONF_CONTROLLER_UID,
    CONF_OUTDOOR,
    CONF_ZONES,
    DOMAIN,
)

AIRFLOW_LIMIT_SELECTOR = NumberSelector(
    NumberSelectorConfig(
        min=0, max=100, step=AIRFLOW_STEP,
        unit_of_measurement="%", mode=NumberSelectorMode.BOX,
    )
)

# Temperature sensors (BoM, Open-Meteo, a local weather station...) or any weather entity
OUTDOOR_SELECTOR = EntitySelector(
    EntitySelectorConfig(
        filter=[
            {"domain": "sensor", "device_class": "temperature"},
            {"domain": "weather"},
        ]
    )
)


def _izone_climates(hass: HomeAssistant) -> list[er.RegistryEntry]:
    return [
        e
        for e in er.async_get(hass).entities.values()
        if e.platform == "izone" and e.domain == "climate" and e.disabled_by is None
    ]


def _controllers(hass: HomeAssistant) -> list[er.RegistryEntry]:
    return [e for e in _izone_climates(hass) if "_z" not in (e.unique_id or "")]


def _zones(hass: HomeAssistant, controller_uid: str) -> list[er.RegistryEntry]:
    prefix = f"{controller_uid}_z"
    return sorted(
        (e for e in _izone_climates(hass) if (e.unique_id or "").startswith(prefix)),
        key=lambda e: e.unique_id,
    )


def _label(hass: HomeAssistant, entry: er.RegistryEntry) -> str:
    if state := hass.states.get(entry.entity_id):
        return state.name
    return entry.name or entry.original_name or entry.entity_id


def _zone_switches(
    hass: HomeAssistant, controller_uid: str, enabled: list[str] | None
) -> tuple[dict[Any, Any], dict[str, str]]:
    """One on/off switch per zone, labelled with the zone name from iZone.

    Returns the schema fields and a map of field key -> zone registry id.
    With enabled=None (first setup) every zone is switched on.
    """
    fields: dict[Any, Any] = {}
    keys: dict[str, str] = {}
    for zone in _zones(hass, controller_uid):
        key = _label(hass, zone)
        while key in keys:  # two zones with the same name
            key = f"{key} "
        keys[key] = zone.id
        on = enabled is None or zone.id in enabled
        fields[vol.Required(key, default=on)] = BooleanSelector()
    return fields, keys


def _enabled_zones(user_input: dict[str, Any], keys: dict[str, str]) -> list[str]:
    return [rid for key, rid in keys.items() if user_input.get(key)]


def _outdoor_field(current_entity_id: str | None):
    return (
        vol.Optional(CONF_OUTDOOR, description={"suggested_value": current_entity_id}),
        OUTDOOR_SELECTOR,
    )


def _store_outdoor(hass: HomeAssistant, entity_id: str | None) -> str | None:
    """Store the registry id when there is one, so renames don't break it."""
    if not entity_id:
        return None
    entry = er.async_get(hass).async_get(entity_id)
    return entry.id if entry else entity_id


def _outdoor_entity_id(hass: HomeAssistant, stored: str | None) -> str | None:
    if not stored:
        return None
    try:
        return er.async_validate_entity_id(er.async_get(hass), stored)
    except vol.Invalid:
        return None


class IZoneAssistantConfigFlow(ConfigFlow, domain=DOMAIN):
    """Pick a controller, the zones, and an optional outdoor temperature source."""

    VERSION = 1

    def __init__(self) -> None:
        self._controller: er.RegistryEntry | None = None
        self._zones: list[str] = []
        self._zone_keys: dict[str, str] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        controllers = _controllers(self.hass)
        if not controllers:
            return self.async_abort(reason="no_controllers")

        if user_input is not None:
            self._controller = next(
                c for c in controllers if c.id == user_input[CONF_CONTROLLER]
            )
            return await self.async_step_zones()

        if len(controllers) == 1:
            self._controller = controllers[0]
            return await self.async_step_zones()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CONTROLLER): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(value=c.id, label=_label(self.hass, c))
                                for c in controllers
                            ]
                        )
                    )
                }
            ),
        )

    async def async_step_zones(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._controller is not None
        await self.async_set_unique_id(self._controller.unique_id)
        self._abort_if_unique_id_configured()

        errors: dict[str, str] = {}
        if user_input is not None:
            self._zones = _enabled_zones(user_input, self._zone_keys)
            if self._zones:
                return await self.async_step_outdoor()
            errors["base"] = "no_zones_enabled"

        fields, self._zone_keys = _zone_switches(
            self.hass, self._controller.unique_id,
            self._zones if user_input is not None else None,
        )
        return self.async_show_form(
            step_id="zones", data_schema=vol.Schema(fields), errors=errors
        )

    async def async_step_outdoor(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._controller is not None
        ctrl = self._controller

        if user_input is not None:
            return self.async_create_entry(
                title=_label(self.hass, ctrl),
                data={
                    CONF_CONTROLLER: ctrl.id,
                    CONF_CONTROLLER_UID: ctrl.unique_id,
                    CONF_ZONES: self._zones,
                    CONF_OUTDOOR: _store_outdoor(self.hass, user_input.get(CONF_OUTDOOR)),
                },
            )

        key, selector = _outdoor_field(None)
        return self.async_show_form(step_id="outdoor", data_schema=vol.Schema({key: selector}))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return IZoneAssistantOptionsFlow()


class IZoneAssistantOptionsFlow(OptionsFlow):
    """Step 1: zones and outdoor source. Step 2: per-zone airflow floor/ceiling."""

    def __init__(self) -> None:
        self._options: dict[str, Any] = {}
        self._zone_keys: dict[str, str] = {}
        self._limit_fields: dict[str, tuple[str, str]] = {}  # field key -> (zone registry id, "floor"/"ceiling")

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self.config_entry
        errors: dict[str, str] = {}
        enabled = entry.options.get(CONF_ZONES, entry.data[CONF_ZONES])
        current_outdoor = _outdoor_entity_id(
            self.hass, entry.options.get(CONF_OUTDOOR, entry.data.get(CONF_OUTDOOR))
        )

        if user_input is not None:
            enabled = _enabled_zones(user_input, self._zone_keys)
            current_outdoor = user_input.get(CONF_OUTDOOR)
            if enabled:
                self._options = {
                    CONF_ZONES: enabled,
                    CONF_OUTDOOR: _store_outdoor(self.hass, current_outdoor),
                }
                return await self.async_step_airflow()
            errors["base"] = "no_zones_enabled"

        fields, self._zone_keys = _zone_switches(
            self.hass, entry.data[CONF_CONTROLLER_UID], enabled
        )
        outdoor_key, outdoor_sel = _outdoor_field(current_outdoor)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({**fields, outdoor_key: outdoor_sel}),
            errors=errors,
        )

    async def async_step_airflow(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Per-zone airflow floor and ceiling (%), e.g. Lounge Room ceiling 90."""
        current = self.config_entry.options.get(CONF_AIRFLOW_LIMITS, {})
        reg = er.async_get(self.hass)
        errors: dict[str, str] = {}
        placeholders = {"zones": ""}

        if user_input is not None:
            limits: dict[str, list[int]] = {}
            for key, (rid, which) in self._limit_fields.items():
                pair = limits.setdefault(rid, [AIRFLOW_FLOOR, AIRFLOW_CEILING])
                pair[0 if which == "floor" else 1] = int(user_input[key])
            bad = [
                _label(self.hass, e)
                for rid, (floor, ceiling) in limits.items()
                if floor >= ceiling and (e := reg.async_get(rid)) is not None
            ]
            if bad:
                errors["base"] = "floor_not_below_ceiling"
                placeholders["zones"] = ", ".join(bad)
            else:
                return self.async_create_entry(
                    data={**self._options, CONF_AIRFLOW_LIMITS: limits}
                )

        # Field labels are the zone names from the iZone controller
        schema: dict[Any, Any] = {}
        self._limit_fields = {}
        for rid in self._options[CONF_ZONES]:
            if (entry := reg.async_get(rid)) is None:
                continue
            name = _label(self.hass, entry)
            floor, ceiling = current.get(rid, (AIRFLOW_FLOOR, AIRFLOW_CEILING))
            for which, default in (("floor", floor), ("ceiling", ceiling)):
                key = f"{name} {which} (%)"
                while key in self._limit_fields:  # two zones with the same name
                    key = f"{key} "
                self._limit_fields[key] = (rid, which)
                schema[vol.Required(key, default=int(default))] = AIRFLOW_LIMIT_SELECTOR

        return self.async_show_form(
            step_id="airflow",
            data_schema=vol.Schema(schema),
            errors=errors,
            description_placeholders=placeholders,
        )
