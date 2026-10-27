# iZone Assistant

<img src="custom_components/izone_assistant/brand/icon.png" alt="iZone Assistant icon" width="96" align="right">

[![Validate](https://github.com/Roving-Ronin/iZone-Assistant/actions/workflows/validate.yaml/badge.svg)](https://github.com/Roving-Ronin/iZone-Assistant/actions/workflows/validate.yaml)
[![Tests](https://github.com/Roving-Ronin/iZone-Assistant/actions/workflows/tests.yaml/badge.svg)](https://github.com/Roving-Ronin/iZone-Assistant/actions/workflows/tests.yaml)
[![GitHub release](https://img.shields.io/github/v/release/Roving-Ronin/iZone-Assistant)](https://github.com/Roving-Ronin/iZone-Assistant/releases)

Extra sensors and controls for Home Assistant's built-in [iZone integration](https://www.home-assistant.io/integrations/izone/), without hand-written template sensors.

Zones are discovered automatically from your iZone controller: there's nothing to count or name.

> iZone Assistant extends Home Assistant's [iZone integration](https://www.home-assistant.io/integrations/izone/). It is not affiliated with or endorsed by iZone.

## What it adds

**Per zone** (attached to each iZone zone device)

| Entity | Notes |
|---|---|
| Temperature | Room temperature, with a `zone_mode` attribute |
| Target temperature | Available only when the zone is in Climate mode |
| Zone mode | Closed / Open / Climate |
| Airflow minimum / maximum | Settable in steps of 5 %, within a per-zone floor and ceiling (default 10–100 %). Minimum can't exceed the current maximum and vice versa |

**Controller** (attached to the iZone controller device)

| Entity | Notes |
|---|---|
| Target temperature | Control zone setpoint, or the unit setpoint when the unit is in control |
| Control zone | Name of the zone currently controlling the unit, or "Unit setpoint" when the controller reports an index beyond its zones (e.g. 13 or 15). The raw 0-based index is in the `control_zone_index` attribute |
| Outdoor temperature | Optional, from any temperature sensor or weather entity you choose |
| HVAC mode *(disabled by default)* | Off / Heat / Cool / Heat/Cool / Dry / Fan only |
| Fan mode *(disabled by default)* | Low / Medium / High / Top / Auto |
| Minimum / Maximum set temperature *(diagnostic, disabled by default)* | |

The disabled-by-default entities duplicate what `climate.izone_controller` already provides (its state and its `fan_mode`, `min_temp` and `max_temp` attributes). Enable them under the entity's settings if you want them as separate entities, e.g. for a clean mode timeline in history.

Supply and return air temperatures are already provided by the iZone integration itself.

## Entity IDs

Entity IDs are prefixed with `izone_` so they don't clash with other sensors in the same room. Zone names come from the names entered on your iZone controller.

| Kind | Pattern | Example |
|---|---|---|
| Zone | `<domain>.izone_<zone>_<entity>` | `sensor.izone_study_temperature`, `number.izone_study_airflow_maximum` |
| Controller | `sensor.izone_controller_<entity>` | `sensor.izone_controller_control_zone`, `sensor.izone_controller_target_temperature` |
| Controller (2+ controllers) | `sensor.izone_controller_<serial>_<entity>` | `sensor.izone_controller_000013170_control_zone` |

Display names are not prefixed (e.g. "Study Temperature"). IDs are set when entities are first created; you can rename them in Home Assistant afterwards.

### Replacing template sensors

If you previously built these with YAML template sensors using the same IDs (e.g. `sensor.izone_study_temperature`), remove those first, then add this integration. Otherwise the new entities get `_2` suffixes.

## Installation

The core iZone integration must already be set up.

### HACS or Home Assistant Marketplace

1. Add `https://github.com/Roving-Ronin/iZone-Assistant` as a custom repository of type **Integration** (HACS → ⋮ → Custom repositories, or the equivalent in the Marketplace).
2. Install **iZone Assistant** and restart Home Assistant.
3. Settings → Devices & services → Add integration → **iZone Assistant**.

### Manual

Copy `custom_components/izone_assistant` into your Home Assistant `config/custom_components/` folder and restart.

## Requirements

- Home Assistant 2026.2 or newer (tested on 2026.2). The integration's own icon shows from 2026.3 onwards.
- The core [iZone integration](https://www.home-assistant.io/integrations/izone/), set up and working.

## Configuration

- **Zones**: all zones are selected by default; untick any you don't want.
- **Outdoor temperature**: optional. Pick a temperature sensor (Bureau of Meteorology, Open-Meteo, a local weather station) or a weather entity.

Both can be changed later from the integration's **Configure** button, which also has an **Airflow limits** step: a floor and ceiling (%) per zone for the airflow controls. Match these to the limits set on your iZone wall panel.

The iZone bridge doesn't report live airflow or damper position, so there is no current-airflow sensor.
