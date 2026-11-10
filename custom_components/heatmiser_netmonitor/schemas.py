"""Shared service-call validators for the Heatmiser NetMonitor integration."""
import voluptuous as vol

from homeassistant.helpers import config_validation as cv

# A target temperature in whole degrees Celsius.
TEMPERATURE = vol.All(vol.Coerce(float), vol.Range(min=5, max=35))

# A time period such as "02:00:00", converted to hours (the NetMonitor works in hours).
HOURS = vol.All(
    cv.time_period,
    cv.positive_timedelta,
    lambda td: td.total_seconds() // 3600,
)
