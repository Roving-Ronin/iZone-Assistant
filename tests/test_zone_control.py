"""Zone mode selects, the Control mode select, Hybrid memory and the safety zone."""

from __future__ import annotations

import pytest

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.izone_assistant.const import DOMAIN

UID = "000013170"
HVAC = {"closed": "off", "open": "fan_only", "climate": "heat_cool"}
SENSORED = ["off", "fan_only", "heat_cool"]
NO_SENSOR = ["off", "fan_only"]

# (name, index, hvac_modes, starting state) - like the real system
ZONES = [
    ("Constant Zone", 0, NO_SENSOR, "fan_only"),
    ("Kitchen Dining", 1, SENSORED, "heat_cool"),
    ("Lounge Room", 2, SENSORED, "heat_cool"),
    ("Study", 3, SENSORED, "off"),
]


async def _setup_system(hass: HomeAssistant, zones=ZONES) -> MockConfigEntry:
    """Fake core iZone (controller + zones, with a working set_hvac_mode) and set up iZone Assistant."""
    hass.config.components.add("izone")
    izone_entry = MockConfigEntry(domain="izone")
    izone_entry.add_to_hass(hass)
    dev_reg, ent_reg = dr.async_get(hass), er.async_get(hass)

    ctrl_dev = dev_reg.async_get_or_create(
        config_entry_id=izone_entry.entry_id, identifiers={("izone", UID)}, name="iZone Controller"
    )
    ent_reg.async_get_or_create(
        "climate", "izone", UID, config_entry=izone_entry, device_id=ctrl_dev.id,
        suggested_object_id="izone_controller",
    )
    hass.states.async_set(
        "climate.izone_controller", "cool",
        {"control_zone": 1, "control_zone_setpoint": None, "temp_setpoint": 21,
         "friendly_name": "iZone Controller"},
    )
    for name, idx, modes, state in zones:
        dev = dev_reg.async_get_or_create(
            config_entry_id=izone_entry.entry_id, identifiers={("izone", UID, idx)},
            name=name, via_device=("izone", UID),
        )
        object_id = name.lower().replace(" ", "_")
        ent_reg.async_get_or_create(
            "climate", "izone", f"{UID}_z{idx + 1}", config_entry=izone_entry,
            device_id=dev.id, suggested_object_id=object_id,
        )
        hass.states.async_set(
            f"climate.{object_id}", state,
            {"hvac_modes": modes, "zone_index": idx, "friendly_name": name,
             "current_temperature": 20.0 if modes == SENSORED else None,
             "airflow_min": 10, "airflow_max": 100},
        )

    calls: list[ServiceCall] = []

    async def set_hvac_mode(call: ServiceCall) -> None:
        calls.append(call)
        eid = call.data["entity_id"]
        eid = eid[0] if isinstance(eid, list) else eid
        old = hass.states.get(eid)
        hass.states.async_set(eid, call.data["hvac_mode"], dict(old.attributes))

    hass.services.async_register("climate", "set_hvac_mode", set_hvac_mode)
    hass.data["test_calls"] = calls

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})  # all zones on
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})  # no outdoor
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    return result["result"]


def _modes(hass: HomeAssistant) -> dict[str, str]:
    return {
        name: hass.states.get(f"select.izone_{name.lower().replace(' ', '_')}_zone_mode").state
        for name, *_ in ZONES
    }


async def _control(hass: HomeAssistant, option: str) -> None:
    await hass.services.async_call(
        "select", "select_option",
        {"entity_id": "select.izone_controller_control_mode", "option": option}, blocking=True,
    )
    await hass.async_block_till_done()


async def _zone(hass: HomeAssistant, name: str, option: str) -> None:
    await hass.services.async_call(
        "select", "select_option",
        {"entity_id": f"select.izone_{name}_zone_mode", "option": option}, blocking=True,
    )
    await hass.async_block_till_done()


def _control_state(hass):
    return hass.states.get("select.izone_controller_control_mode")


async def test_selects_created(hass: HomeAssistant) -> None:
    await _setup_system(hass)
    study = hass.states.get("select.izone_study_zone_mode")
    assert study.state == "closed" and study.attributes["options"] == ["closed", "open", "climate"]
    assert study.name == "Study Zone mode"
    constant = hass.states.get("select.izone_constant_zone_zone_mode")
    assert constant.attributes["options"] == ["closed", "open"]  # no sensor, no Climate
    ctrl = _control_state(hass)
    assert ctrl.attributes["options"] == ["local", "master", "hybrid", "closed"]
    assert ctrl.state == "hybrid"  # Study is closed while others aren't
    assert ctrl.attributes["constant_zone"] == "climate.constant_zone"  # auto-detected
    assert ctrl.attributes["safety_zone"] == "climate.constant_zone"  # constant zone is Open


async def test_zone_select_changes_only_that_zone(hass: HomeAssistant) -> None:
    await _setup_system(hass)
    await _zone(hass, "study", "climate")
    assert hass.states.get("climate.study").state == "heat_cool"
    assert _modes(hass) == {"Constant Zone": "open", "Kitchen Dining": "climate",
                            "Lounge Room": "climate", "Study": "climate"}
    assert _control_state(hass).state == "local"  # sensored all Climate, constant Open


async def test_control_modes(hass: HomeAssistant) -> None:
    await _setup_system(hass)

    await _control(hass, "master")
    assert set(_modes(hass).values()) == {"open"}
    assert _control_state(hass).state == "master"

    await _control(hass, "local")
    assert _modes(hass) == {"Constant Zone": "open", "Kitchen Dining": "climate",
                            "Lounge Room": "climate", "Study": "climate"}
    assert _control_state(hass).state == "local"

    # Closed with the constant zone Open: only the constant zone stays open
    await _control(hass, "closed")
    assert _modes(hass) == {"Constant Zone": "open", "Kitchen Dining": "closed",
                            "Lounge Room": "closed", "Study": "closed"}
    assert _control_state(hass).state == "closed"


async def test_closed_with_constant_zone_closed_keeps_control_zone_open(hass: HomeAssistant) -> None:
    await _setup_system(hass)
    await _zone(hass, "constant_zone", "closed")
    await _control(hass, "closed")
    # Constant zone stays closed; the control zone (Kitchen Dining, index 1) stays open
    assert _modes(hass) == {"Constant Zone": "closed", "Kitchen Dining": "open",
                            "Lounge Room": "closed", "Study": "closed"}
    assert _control_state(hass).state == "closed"
    assert _control_state(hass).attributes["safety_zone"] == "climate.kitchen_dining"


async def test_hybrid_restores_individual_modes(hass: HomeAssistant) -> None:
    entry = await _setup_system(hass)
    # Individual changes: one from HA, one from the wall panel (state change only)
    await _zone(hass, "lounge_room", "open")
    attrs = dict(hass.states.get("climate.study").attributes)
    hass.states.async_set("climate.study", "heat_cool", attrs)
    await hass.async_block_till_done()
    before = _modes(hass)
    assert before == {"Constant Zone": "open", "Kitchen Dining": "climate",
                      "Lounge Room": "open", "Study": "climate"}

    await _control(hass, "closed")   # bulk changes aren't remembered...
    await _control(hass, "master")
    await _control(hass, "hybrid")   # ...so Hybrid puts the individual modes back
    assert _modes(hass) == before

    # Remembered modes survive a reload, even when the zones are in a bulk mode at the time
    await _control(hass, "master")
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert set(_modes(hass).values()) == {"open"}
    await _control(hass, "hybrid")
    assert _modes(hass) == before


async def test_safety_zone_on_individual_close(hass: HomeAssistant) -> None:
    await _setup_system(hass)
    await _zone(hass, "constant_zone", "closed")
    await _zone(hass, "lounge_room", "closed")
    await _zone(hass, "study", "closed")
    # Only Kitchen Dining (the control zone, and now the safety zone) is open
    with pytest.raises(HomeAssistantError, match="must stay open"):
        await _zone(hass, "kitchen_dining", "closed")
    assert _modes(hass)["Kitchen Dining"] == "climate"

    # Closing the last open zone when it isn't the safety zone opens the safety zone
    await _zone(hass, "lounge_room", "open")
    await _zone(hass, "kitchen_dining", "closed")  # allowed: Lounge Room is open
    await _zone(hass, "lounge_room", "closed")     # would leave nothing open
    assert _modes(hass) == {"Constant Zone": "closed", "Kitchen Dining": "open",
                            "Lounge Room": "closed", "Study": "closed"}


async def test_constant_zone_override_none(hass: HomeAssistant) -> None:
    entry = await _setup_system(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    fields = {str(k): k for k in result["data_schema"].schema}
    detected = er.async_get(hass).async_get("climate.constant_zone").id
    assert fields["constant_zone"].default() == detected  # pre-filled from auto-detect
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"constant_zone": "none"}
    )
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    ctrl = _control_state(hass)
    assert ctrl.attributes["constant_zone"] is None
    assert ctrl.attributes["safety_zone"] == "climate.kitchen_dining"
    # Without a constant zone, Closed keeps the control zone open and closes the rest
    await _control(hass, "closed")
    assert _modes(hass) == {"Constant Zone": "closed", "Kitchen Dining": "open",
                            "Lounge Room": "closed", "Study": "closed"}


async def test_old_zone_mode_sensors_removed(hass: HomeAssistant) -> None:
    """Upgrading from a version with sensor.izone_<zone>_zone_mode."""
    entry = await _setup_system(hass)
    ent_reg = er.async_get(hass)
    ent_reg.async_get_or_create(
        "sensor", DOMAIN, f"{UID}_z4_zone_mode", config_entry=entry,
        suggested_object_id="izone_study_zone_mode",
    )
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert ent_reg.async_get("sensor.izone_study_zone_mode") is None
    assert hass.states.get("select.izone_study_zone_mode") is not None


async def test_set_temperature_number_removed_on_upgrade(hass: HomeAssistant) -> None:
    """v0.5.0 created number.izone_controller_set_temperature; later versions remove it."""
    entry = await _setup_system(hass)
    ent_reg = er.async_get(hass)
    ent_reg.async_get_or_create(
        "number", DOMAIN, f"{UID}_set_temperature", config_entry=entry,
        suggested_object_id="izone_controller_set_temperature",
    )
    assert ent_reg.async_get("number.izone_controller_set_temperature") is not None
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert ent_reg.async_get("number.izone_controller_set_temperature") is None
    # Airflow numbers are kept
    assert hass.states.get("number.izone_study_airflow_maximum") is not None
