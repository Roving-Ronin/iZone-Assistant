"""End-to-end test: fake iZone climate entities -> config flow -> derived entities."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.izone_assistant.const import CONF_OUTDOOR, DOMAIN

UID = "000013170"


async def _fake_izone(hass: HomeAssistant) -> None:
    """Register a controller and two zones the way core's iZone integration does."""
    hass.config.components.add("izone")  # satisfy the manifest dependency without real hardware
    izone_entry = MockConfigEntry(domain="izone")
    izone_entry.add_to_hass(hass)
    dev_reg, ent_reg = dr.async_get(hass), er.async_get(hass)

    ctrl_dev = dev_reg.async_get_or_create(
        config_entry_id=izone_entry.entry_id, identifiers={("izone", UID)},
        name=f"iZone Controller {UID}",
    )
    ent_reg.async_get_or_create(
        "climate", "izone", UID, config_entry=izone_entry, device_id=ctrl_dev.id,
        suggested_object_id="izone_controller",
    )
    hass.states.async_set(
        "climate.izone_controller", "cool",
        {"fan_mode": "high", "min_temp": 15, "max_temp": 30,
         "control_zone": 1, "control_zone_setpoint": 22.5, "temp_setpoint": 24,
         "friendly_name": "iZone Controller"},
    )

    for n, (name, state, idx, attrs) in enumerate(
        [
            ("Study", "heat_cool", 0, {"temperature": 21.0}),
            ("Lounge Room", "fan_only", 1, {}),
        ],
        start=1,
    ):
        dev = dev_reg.async_get_or_create(
            config_entry_id=izone_entry.entry_id,
            identifiers={("izone", UID, idx)}, name=name, via_device=("izone", UID),
        )
        object_id = name.lower().replace(" ", "_")
        ent_reg.async_get_or_create(
            "climate", "izone", f"{UID}_z{n}", config_entry=izone_entry,
            device_id=dev.id, suggested_object_id=object_id,
        )
        hass.states.async_set(
            f"climate.{object_id}", state,
            {"current_temperature": 20.0 + n, "airflow_min": 10, "airflow_max": 90,
             "zone_index": idx, "friendly_name": name,
             "hvac_modes": ["off", "fan_only", "heat_cool"], **attrs},
        )

    hass.states.async_set(
        "sensor.goulburn_temperature", "14.2",
        {"device_class": "temperature", "unit_of_measurement": "°C"},
    )


async def _setup(hass: HomeAssistant, outdoor: str | None = "sensor.goulburn_temperature"):
    """Run the config flow with all zones selected; returns the config entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    if result["step_id"] == "user":  # more than one controller
        ctrl_id = er.async_get(hass).async_get("climate.izone_controller").id
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"controller": ctrl_id}
        )
    assert result["step_id"] == "zones"
    # One on/off switch per zone, labelled with the iZone zone name, all on by default
    switches = {str(k): k.default() for k in result["data_schema"].schema}
    assert switches["Study"] is True and switches["Lounge Room"] is True
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "outdoor"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_OUTDOOR: outdoor} if outdoor else {}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    return result["result"]


def _ours(hass: HomeAssistant) -> dict[str, er.RegistryEntry]:
    return {
        e.entity_id: e for e in er.async_get(hass).entities.values() if e.platform == DOMAIN
    }


async def test_flow_and_entities(hass: HomeAssistant) -> None:
    await _fake_izone(hass)
    calls: list[ServiceCall] = []

    async def _record(call: ServiceCall) -> None:
        calls.append(call)

    hass.services.async_register("izone", "airflow_min", _record)
    hass.services.async_register("izone", "airflow_max", _record)

    entry = await _setup(hass)
    ours = _ours(hass)
    state = hass.states.get

    # Entity IDs: izone_<zone>_* for zones, izone_controller_* for the controller
    assert set(ours) == {
        "sensor.izone_study_temperature",
        "sensor.izone_study_target_temperature",
        "sensor.izone_study_zone_mode",
        "number.izone_study_airflow_minimum",
        "number.izone_study_airflow_maximum",
        "sensor.izone_lounge_room_temperature",
        "sensor.izone_lounge_room_target_temperature",
        "sensor.izone_lounge_room_zone_mode",
        "number.izone_lounge_room_airflow_minimum",
        "number.izone_lounge_room_airflow_maximum",
        "sensor.izone_controller_hvac_mode",
        "sensor.izone_controller_fan_mode",
        "sensor.izone_controller_target_temperature",
        "sensor.izone_controller_minimum_set_temperature",
        "sensor.izone_controller_maximum_set_temperature",
        "sensor.izone_controller_control_zone",
        "sensor.izone_controller_outdoor_temperature",
    }

    # Redundant controller entities are disabled by default; min/max are diagnostic
    disabled = {eid for eid, e in ours.items() if e.disabled_by is not None}
    assert disabled == {
        "sensor.izone_controller_hvac_mode",
        "sensor.izone_controller_fan_mode",
        "sensor.izone_controller_minimum_set_temperature",
        "sensor.izone_controller_maximum_set_temperature",
    }
    assert ours["sensor.izone_controller_minimum_set_temperature"].entity_category == EntityCategory.DIAGNOSTIC
    assert ours["sensor.izone_controller_hvac_mode"].entity_category is None
    assert all(state(eid) is None for eid in disabled)

    # Zone values
    assert state("sensor.izone_study_temperature").state == "21.0"
    assert state("sensor.izone_study_temperature").name == "Study Temperature"
    assert state("sensor.izone_study_temperature").attributes["zone_mode"] == "Climate"
    assert state("sensor.izone_study_target_temperature").state == "21.0"
    assert state("sensor.izone_study_zone_mode").state == "climate"
    assert state("sensor.izone_lounge_room_target_temperature").state == "unavailable"
    assert state("sensor.izone_lounge_room_zone_mode").state == "open"

    # Controller values (enabled by default)
    assert state("sensor.izone_controller_target_temperature").state == "22.5"
    assert state("sensor.izone_controller_control_zone").state == "Lounge Room"
    assert state("sensor.izone_controller_outdoor_temperature").state == "14.2"

    # Enabling the disabled ones works
    ent_reg = er.async_get(hass)
    for eid in disabled:
        ent_reg.async_update_entity(eid, disabled_by=None)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert state("sensor.izone_controller_hvac_mode").state == "cool"
    assert state("sensor.izone_controller_fan_mode").state == "high"
    assert state("sensor.izone_controller_minimum_set_temperature").state == "15.0"
    assert state("sensor.izone_controller_maximum_set_temperature").state == "30.0"

    # Entities sit under the existing iZone devices (so they group and get the area)...
    ours = _ours(hass)
    dev_reg = dr.async_get(hass)
    study_dev = dev_reg.async_get(ours["sensor.izone_study_zone_mode"].device_id)
    assert study_dev.name == "Study"
    assert (
        dev_reg.async_get(ours["sensor.izone_controller_outdoor_temperature"].device_id).name
        == f"iZone Controller {UID}"
    )
    assert all(e.device_id for e in ours.values())
    # ...with device-based display names...
    assert state("number.izone_study_airflow_maximum").name == "Study Airflow maximum"
    assert state("sensor.izone_controller_control_zone").name == f"iZone Controller {UID} Control zone"
    # ...without adding this integration to iZone's devices
    assert entry.entry_id not in study_dev.config_entries

    # Airflow numbers: default 10-100 limits, safety net and service call
    amax = state("number.izone_study_airflow_maximum")
    amin = state("number.izone_study_airflow_minimum")
    assert amax.state == "90.0" and amax.attributes["min"] == 10 and amax.attributes["max"] == 100
    assert amin.attributes["max"] == 90  # can't exceed current maximum
    await hass.services.async_call(
        "number", "set_value", {"entity_id": amax.entity_id, "value": 80}, blocking=True
    )
    assert calls[-1].service == "airflow_max" and calls[-1].data["airflow"] == 80

    # Live updates
    hass.states.async_set("climate.study", "off", {**state("climate.study").attributes})
    await hass.async_block_till_done()
    assert state("sensor.izone_study_zone_mode").state == "closed"
    assert state("sensor.izone_study_target_temperature").state == "unavailable"


async def test_airflow_limits_options(hass: HomeAssistant) -> None:
    await _fake_izone(hass)
    entry = await _setup(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init"
    assert [str(k) for k in result["data_schema"].schema] == ["Study", "Lounge Room", CONF_OUTDOOR]
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"Study": True, "Lounge Room": True, CONF_OUTDOOR: "sensor.goulburn_temperature"},
    )
    assert result["step_id"] == "airflow"
    fields = [str(k) for k in result["data_schema"].schema]
    assert fields == [
        "Study floor (%)", "Study ceiling (%)",
        "Lounge Room floor (%)", "Lounge Room ceiling (%)",
    ]

    # Floor must be below ceiling
    bad = {"Study floor (%)": 50, "Study ceiling (%)": 50,
           "Lounge Room floor (%)": 10, "Lounge Room ceiling (%)": 90}
    result = await hass.config_entries.options.async_configure(result["flow_id"], bad)
    assert result["errors"] == {"base": "floor_not_below_ceiling"}
    assert result["description_placeholders"]["zones"] == "Study"

    good = {**bad, "Study floor (%)": 20, "Study ceiling (%)": 100}
    result = await hass.config_entries.options.async_configure(result["flow_id"], good)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()  # entry reloads with the new limits

    state = hass.states.get
    lmax = state("number.izone_lounge_room_airflow_maximum")
    assert lmax.attributes["max"] == 90 and lmax.attributes["ceiling"] == 90
    smin = state("number.izone_study_airflow_minimum")
    assert smin.attributes["min"] == 20 and smin.attributes["floor"] == 20

    # Re-opening options shows the saved limits as defaults
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_OUTDOOR: "sensor.goulburn_temperature"}
    )
    defaults = {str(k): k.default() for k in result["data_schema"].schema}
    assert defaults["Lounge Room ceiling (%)"] == 90 and defaults["Study floor (%)"] == 20


async def test_second_controller_gets_serial_prefix(hass: HomeAssistant) -> None:
    await _fake_izone(hass)
    er.async_get(hass).async_get_or_create(
        "climate", "izone", "000099999", suggested_object_id="izone_controller_2"
    )
    await _setup(hass, outdoor=None)

    assert hass.states.get(f"sensor.izone_controller_{UID}_control_zone").state == "Lounge Room"
    assert hass.states.get(f"sensor.izone_controller_{UID}_target_temperature").state == "22.5"
    # Zone IDs are unaffected
    assert hass.states.get("sensor.izone_study_zone_mode").state == "climate"


async def test_control_zone_and_target_like_real_controller(hass: HomeAssistant) -> None:
    """Mirrors a real controller: control_zone 1, control_zone_setpoint null, temp_setpoint tracks the zone."""
    await _fake_izone(hass)
    # A third zone the iZone integration created but which has no state (e.g. disabled/not loaded)
    er.async_get(hass).async_get_or_create(
        "climate", "izone", f"{UID}_z3", suggested_object_id="bedroom_3"
    )
    await _setup(hass, outdoor=None)
    state = hass.states.get
    ctrl = "climate.izone_controller"

    def set_ctrl(**attrs):
        hass.states.async_set(ctrl, "cool", {**state(ctrl).attributes, **attrs})

    # Real-world readings: zone 1 in control, core reports no control_zone_setpoint
    set_ctrl(control_zone=1, control_zone_setpoint=None, temp_setpoint=19.5)
    await hass.async_block_till_done()
    assert state("sensor.izone_controller_control_zone").state == "Lounge Room"
    assert state("sensor.izone_controller_target_temperature").state == "19.5"
    assert state("sensor.izone_controller_control_zone").attributes["control_zone_index"] == 1

    # Index in range (3 zones) but no entity state: panel number (1-based)
    set_ctrl(control_zone=2)
    await hass.async_block_till_done()
    assert state("sensor.izone_controller_control_zone").state == "Zone 3"

    # Beyond the zone count: unit setpoint
    for idx in (3, 13, 15):
        set_ctrl(control_zone=idx)
        await hass.async_block_till_done()
        assert state("sensor.izone_controller_control_zone").state == "Unit setpoint"


async def test_existing_entities_without_device_get_linked(hass: HomeAssistant) -> None:
    """Entities created by an earlier version with no device are moved under the zone device."""
    await _fake_izone(hass)
    entry = await _setup(hass)
    ent_reg = er.async_get(hass)
    eid = "number.izone_study_airflow_maximum"
    ent_reg.async_update_entity(eid, device_id=None)
    assert ent_reg.async_get(eid).device_id is None

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    device = dr.async_get(hass).async_get(ent_reg.async_get(eid).device_id)
    assert device is not None and device.name == "Study"
    assert hass.states.get(eid).name == "Study Airflow maximum"


async def test_zone_switches(hass: HomeAssistant) -> None:
    """Switching a zone off removes its entities; all off is refused."""
    await _fake_izone(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    # Every zone off -> error, form shown again
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"Study": False, "Lounge Room": False}
    )
    assert result["step_id"] == "zones" and result["errors"] == {"base": "no_zones_enabled"}
    # Study only
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"Study": True, "Lounge Room": False}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    entry = result["result"]
    await hass.async_block_till_done()
    ours = _ours(hass)
    assert "sensor.izone_study_temperature" in ours
    assert not any("lounge_room" in eid for eid in ours)

    # Options: switches reflect the saved choice; turning Lounge Room on adds it
    result = await hass.config_entries.options.async_init(entry.entry_id)
    defaults = {str(k): k.default() for k in result["data_schema"].schema if str(k) != CONF_OUTDOOR}
    assert defaults == {"Study": True, "Lounge Room": False}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"Study": True, "Lounge Room": True}
    )
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert hass.states.get("sensor.izone_lounge_room_zone_mode").state == "open"


async def test_constant_zone(hass: HomeAssistant) -> None:
    """A zone without a sensor: no target, temperature disabled by default and 0 when enabled."""
    await _fake_izone(hass)
    izone_entry = hass.config_entries.async_entries("izone")[0]
    dev = dr.async_get(hass).async_get_or_create(
        config_entry_id=izone_entry.entry_id, identifiers={("izone", UID, 2)},
        name="Constant Zone", via_device=("izone", UID),
    )
    er.async_get(hass).async_get_or_create(
        "climate", "izone", f"{UID}_z3", config_entry=izone_entry, device_id=dev.id,
        suggested_object_id="constant_zone",
    )
    hass.states.async_set(
        "climate.constant_zone", "fan_only",
        {"hvac_modes": ["off", "fan_only"], "current_temperature": None,
         "airflow_min": 20, "airflow_max": 100, "zone_index": 2,
         "friendly_name": "Constant Zone"},
    )
    entry = await _setup(hass)
    ent_reg = er.async_get(hass)
    ours = _ours(hass)
    state = hass.states.get

    assert "sensor.izone_constant_zone_target_temperature" not in ours
    temp = ours["sensor.izone_constant_zone_temperature"]
    assert temp.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert state("sensor.izone_constant_zone_zone_mode").state == "open"
    assert state("number.izone_constant_zone_airflow_minimum").state == "20.0"
    # Sensored zones are unaffected
    assert ours["sensor.izone_study_temperature"].disabled_by is None
    assert "sensor.izone_study_target_temperature" in ours

    # A Target temperature left over from an earlier version is removed; enabling
    # the temperature sensor gives 0 while the zone has no reading
    ent_reg.async_get_or_create(
        "sensor", DOMAIN, f"{UID}_z3_zone_target_temperature", config_entry=entry,
        suggested_object_id="izone_constant_zone_target_temperature",
    )
    ent_reg.async_update_entity("sensor.izone_constant_zone_temperature", disabled_by=None)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert "sensor.izone_constant_zone_target_temperature" not in _ours(hass)
    assert state("sensor.izone_constant_zone_temperature").state == "0.0"
    assert state("sensor.izone_constant_zone_temperature").attributes["has_sensor"] is False
    assert "state_class" not in state("sensor.izone_constant_zone_temperature").attributes
    assert state("sensor.izone_study_temperature").attributes["state_class"] == "measurement"

    # If a reading appears (sensor fitted later), it's reported
    hass.states.async_set(
        "climate.constant_zone", "fan_only",
        {**state("climate.constant_zone").attributes, "current_temperature": 19.5},
    )
    await hass.async_block_till_done()
    assert state("sensor.izone_constant_zone_temperature").state == "19.5"


async def test_sensored_zone_open_keeps_temperature(hass: HomeAssistant) -> None:
    """A zone with a sensor set to Open: temperature keeps reporting, target unavailable."""
    await _fake_izone(hass)
    await _setup(hass)
    state = hass.states.get
    # Lounge Room is a sensored zone currently set to Open (fan_only)
    assert state("sensor.izone_lounge_room_temperature").state == "22.0"
    assert state("sensor.izone_lounge_room_target_temperature").state == "unavailable"
    assert state("sensor.izone_lounge_room_zone_mode").state == "open"
