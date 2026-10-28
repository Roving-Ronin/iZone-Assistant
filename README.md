# <img src="https://brands.home-assistant.io/_/izone/logo.png" alt="iZone" height="40"> iZone Assistant

[![release](https://img.shields.io/github/v/release/Roving-Ronin/iZone-Assistant?style=flat-square&color=green)](https://github.com/Roving-Ronin/iZone-Assistant/releases)
[![downloads](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/Roving-Ronin/iZone-Assistant/badges/downloads.json&style=flat-square)](https://github.com/Roving-Ronin/iZone-Assistant/releases)
[![HACS](https://img.shields.io/badge/HACS-Custom-orange?style=flat-square)](https://hacs.xyz)
![maintained](https://img.shields.io/badge/maintained-yes-brightgreen?style=flat-square)
[![commit activity](https://img.shields.io/github/commit-activity/y/Roving-Ronin/iZone-Assistant?style=flat-square)](https://github.com/Roving-Ronin/iZone-Assistant/commits/main)
[![Validate](https://img.shields.io/github/actions/workflow/status/Roving-Ronin/iZone-Assistant/validate.yaml?branch=main&label=validate&style=flat-square)](https://github.com/Roving-Ronin/iZone-Assistant/actions/workflows/validate.yaml)
[![Tests](https://img.shields.io/github/actions/workflow/status/Roving-Ronin/iZone-Assistant/tests.yaml?branch=main&label=tests&style=flat-square)](https://github.com/Roving-Ronin/iZone-Assistant/actions/workflows/tests.yaml)
[![license](https://img.shields.io/github/license/Roving-Ronin/iZone-Assistant?style=flat-square)](LICENSE)


> iZone Assistant extends Home Assistant's [iZone integration](https://www.home-assistant.io/integrations/izone/). It is not affiliated with or endorsed by iZone.

Extra sensors and controls for Home Assistant's built-in [iZone integration](https://www.home-assistant.io/integrations/izone/), without hand-written template sensors.

Zones are discovered automatically from your iZone controller: there's nothing to count or name.

## What it adds

**Per zone** (attached to each iZone zone device)

| Entity | Notes |
|---|---|
| Temperature | Room temperature, with a `zone_mode` attribute. Keeps reporting when a sensored zone is set to Open or Closed. For zones without a sensor (constant, open/close) it's disabled by default; if enabled it shows 0 until a reading exists |
| Target temperature | Zones with a sensor only, shown in every zone mode. Home Assistant only exposes a zone's setpoint while it's in Climate mode, so while it's Open or Closed this shows the last setpoint seen (attribute `live: false`) |
| Zone mode (select) | Closed / Open / Climate (Closed / Open for zones without a sensor). Changes only that zone |
| Airflow minimum / maximum | Settable in steps of 5 %, within a per-zone floor and ceiling (default 10–100 %). Minimum can't exceed the current maximum and vice versa |

**Controller** (attached to the iZone controller device)

| Entity | Notes |
|---|---|
| Target temperature | Control zone setpoint, or the unit setpoint when the unit is in control |
| Set temperature (number) | Sets the unit's target from one place: while a zone is in control and in Climate (Local / Hybrid) it changes that zone's target, otherwise (Master / Closed) the unit setpoint. The `applies_to` attribute shows which. Use this rather than the iZone controller entity's own target, which the controller overwrites with the control zone's target in zones mode |
| Control mode (select) | **Local** (sensored zones Climate, others Open: iZone's zones mode), **Master** (all zones Open: the wall controller or return air sensor drives the unit), **Hybrid** (each zone back to the last mode it was given individually), **Closed** (all zones closed except the safety zone) |
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

1. Make sure the core iZone integration is set up:
   - [![Add the iZone integration to Home Assistant.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start?domain=izone)
2. Install this integration with HACS (or the Home Assistant Marketplace):
   - [![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Roving-Ronin&repository=iZone-Assistant&category=integration)
   - Or manually: download `izone_assistant.zip` from the [latest release](https://github.com/Roving-Ronin/iZone-Assistant/releases/latest) and unzip it into `config/custom_components/izone_assistant/`.
3. Restart Home Assistant.
4. Start the configuration flow:
   - [![Start Config Flow](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start?domain=izone_assistant)
   - Or: go to **Settings** → **Devices & services**, click **+ Add Integration**, and select **iZone Assistant** from the list.

## Requirements

- Home Assistant 2026.2 or newer (tested on 2026.2). The integration's own icon shows from 2026.3 onwards.
- The core [iZone integration](https://www.home-assistant.io/integrations/izone/), set up and working.

## Configuration

- **Zones**: all zones are selected by default; untick any you don't want.
- **Outdoor temperature**: optional. Pick a temperature sensor (Bureau of Meteorology, Open-Meteo, a local weather station) or a weather entity.

Both can be changed later from **Settings → Devices & services → iZone Assistant → Configure**, which also has an **Airflow limits** step: a floor and ceiling (%) per zone for the airflow controls. Match these to the limits set on your iZone wall panel.

**Constant zone** (in Configure): detected automatically from the zone iZone names "Constant Zone"; choose another zone, or None, if yours differs.

### Safety zone

So the ducting always has somewhere to push air, one zone is kept open whether the unit is on or off: the constant zone if there is one and it's Open, otherwise the controller's current control zone. **Control mode → Closed** leaves it open, and a zone's own select won't close it if it's the last open zone. Changes made on the wall panel or tablet aren't overridden.

The iZone bridge doesn't report live airflow or damper position, so there is no current-airflow sensor.

## Releasing (maintainers)

Draft a new GitHub release, create a tag such as `v0.3.0` on `main`, and publish. The release workflow takes the version from the tag, writes it into `manifest.json`, attaches `izone_assistant.zip` to the release, and commits the version back to `main`. There's no need to edit `manifest.json` by hand. Mark betas as a pre-release (e.g. `v0.4.0b1`); they don't change the version on `main`.
