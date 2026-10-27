"""Constants for iZone Assistant."""

DOMAIN = "izone_assistant"

CONF_CONTROLLER = "controller"          # entity registry id of the iZone controller climate entity
CONF_CONTROLLER_UID = "controller_uid"  # iZone device uid (controller climate unique_id)
CONF_ZONES = "zones"                    # list of entity registry ids of zone climate entities
CONF_OUTDOOR = "outdoor_temperature"    # optional temperature sensor or weather entity
CONF_AIRFLOW_LIMITS = "airflow_limits"  # {zone registry id: [floor, ceiling]}

# Zone climate state -> zone mode
ZONE_MODE_MAP = {
    "off": "closed",
    "fan_only": "open",
    "heat_cool": "climate",
    "auto": "climate",
}
ZONE_MODES = ["closed", "open", "climate"]
CLIMATE_STATES = {"heat_cool", "auto"}

# Controller climate states / fan modes as reported by core's iZone integration
HVAC_MODES = ["off", "heat", "cool", "heat_cool", "dry", "fan_only"]
FAN_MODES = ["low", "medium", "high", "top", "auto"]

# Entity ID suffix per entity key: izone_<zone>_<suffix> for zones, izone_<suffix> for the controller
OBJECT_SUFFIX = {
    "zone_temperature": "temperature",
    "zone_target_temperature": "target_temperature",
    "zone_mode": "zone_mode",
    "airflow_min": "airflow_minimum",
    "airflow_max": "airflow_maximum",
    "hvac_mode": "hvac_mode",
    "fan_mode": "fan_mode",
    "controller_target_temperature": "target_temperature",
    "min_set_temperature": "minimum_set_temperature",
    "max_set_temperature": "maximum_set_temperature",
    "control_zone": "control_zone",
    "outdoor_temperature": "outdoor_temperature",
}
OBJECT_PREFIX = "izone"

# Default airflow hard limits (%), overridable per zone in options.
# Safety net: min <= current max, max >= current min.
AIRFLOW_FLOOR = 10
AIRFLOW_CEILING = 100
AIRFLOW_STEP = 5
