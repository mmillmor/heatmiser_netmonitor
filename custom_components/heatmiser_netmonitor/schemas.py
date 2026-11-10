"""Shared service-call validators for the Heatmiser NetMonitor integration."""
import voluptuous as vol

# A target temperature in whole degrees Celsius.
TEMPERATURE = vol.All(vol.Coerce(float), vol.Range(min=5, max=35))


def _whole_hours(value: float) -> int:
    """Accept only whole numbers of hours."""
    if value != int(value):
        raise vol.Invalid("Hours must be a whole number")
    return int(value)


# A number of whole hours for a boost or hold: 0 cancels, otherwise 1 to 99.
HOURS = vol.All(vol.Coerce(float), vol.Range(min=0, max=99), _whole_hours)
