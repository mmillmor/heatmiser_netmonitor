"""Config flow for Heatmiser NetMonitor integration."""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime

import requests
from requests.auth import HTTPBasicAuth

from homeassistant.components.climate.const import (
    HVACAction,
    HVACMode
)
from homeassistant.const import (
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE
)
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Number of stat positions in the NetMonitor's quick-set bitmap.
QUICKSET_SLOTS = 32
# Commands are repeated because communication with the stats is unreliable.
SEND_ATTEMPTS = 10
# Seconds to wait for the NetMonitor to answer a request.
REQUEST_TIMEOUT = 10



class HeatmiserStat:
    """Utility class for Heatmiser NetMonitor stats."""

    def __init__(
        self,
        id,
        name,
        current_temperature,
        target_temperature,
        hvac_mode,
        current_state,
        hw_timer_output,
        hw_boost_time,
    ):
        """Initialize the stat."""
        self.id = id
        self.name = name
        self.current_temperature = current_temperature
        self.target_temperature = target_temperature
        self.hvac_mode = hvac_mode
        self.current_state = current_state
        self.hw_timer_output=hw_timer_output
        self.hw_boost_time=hw_boost_time


class HeatmiserHub:
    """Heatmiser Hub controller."""

    def __init__(
        self, host: str, username: str, password: str, hass: HomeAssistant
    ) -> None:
        """Initialize the hub controller."""
        self.host = host
        self.username = username
        self.password = password
        self.hass = hass
        # The NetMonitor keeps a "currently selected stat" server-side, so
        # requests must not interleave.
        self._lock = asyncio.Lock()

    def _get(self, page):
        """GET a NetMonitor page."""
        return requests.get(
            "http://" + self.host + "/" + page,
            auth=HTTPBasicAuth(self.username, self.password),
            timeout=REQUEST_TIMEOUT,
        )

    def _post(self, page, data):
        """POST a form to a NetMonitor page."""
        return requests.post(
            "http://" + self.host + "/" + page,
            data=data,
            auth=HTTPBasicAuth(self.username, self.password),
            timeout=REQUEST_TIMEOUT,
        )

    def _send_repeatedly(self, send):
        """Call send() several times, as communication with the stats is unreliable.

        Individual failures are logged; an error is raised only if every
        attempt fails.
        """
        sent = 0
        last_error = None
        for attempt in range(SEND_ATTEMPTS):
            if attempt:
                time.sleep(1)
            try:
                send()
                sent += 1
            except requests.RequestException as err:
                last_error = err
                _LOGGER.warning(
                    "Attempt %d of %d failed: %s", attempt + 1, SEND_ATTEMPTS, err
                )
        if not sent:
            raise last_error

    def _set_stat_value(self, name, data):
        """Select a stat, then send it a setting, repeating to make sure it lands."""

        def send():
            if self._post("right.htm", {"rdbkck": "1", "curSelStat": name}).status_code == 200:
                self._post("right.htm", data)

        self._send_repeatedly(send)

    def async_auth(self) -> bool:
        """Validate the username, password and host."""

        response = self._get("quickview.htm")
        if response.status_code in (401, 403):
            return False
        response.raise_for_status()
        return True

    async def authenticate(self) -> bool:
        """Validate the username, password and host asynchronously.

        Raises requests.RequestException if the device cannot be reached.
        """
        return await self.hass.async_add_executor_job(self.async_auth)

    def set_time(self):
        """Get the networkSetup."""

        response = self._get("networkSetup.htm")

        if response.status_code == 200:
            content = response.content.decode("utf-8")
            formValues = content.split('input type=hidden name="')
            ip=formValues[4].split('"')[2]
            mask=formValues[5].split('"')[2]
            gate=formValues[6].split('"')[2]
            dns=formValues[7].split('"')[2]
            gmtflag=formValues[11].split('"')[2]
            pin=formValues[12].split('"')[2]
            localTime=datetime.now()
            timeStr=localTime.strftime("%H:%M")
            dateStr=localTime.strftime("%d/%m/%Y")
            postData={"rdbkck": 0
		    ,"lognm":self.username
		    ,"logpd":self.password
		    ,"ip":ip
		    ,"mask":mask
		    ,"gate":gate
		    ,"dns":dns
		    ,"timestr":timeStr
		    ,"datestr":dateStr
		    ,"timeflag":1
		    ,"gmtflag":1
		    ,"pin":pin}

            self._post("networkSetup.htm", postData)
    
    async def set_time_async(self):
        """Set the time asynchronously."""
        async with self._lock:
            return await self.hass.async_add_executor_job(self.set_time)

    def set_boost(self, name, hours):
        """Set a hot water boost time."""
        self._set_stat_value(name, {"hwBoost": '{0:02d}'.format(int(hours))})
    
    async def set_boost_async(self,name,hours):
        """Set the time asynchronously."""
        async with self._lock:
            return await self.hass.async_add_executor_job(self.set_boost, name, hours)


    def set_holiday(self, start_date_time, end_date_time):
        """Set a holiday."""
        self._post("holiday.htm", {
            "rdbkck": "0",
            "starttime": start_date_time.strftime("%H.%M"),
            "startdate": start_date_time.strftime("%d.%m.%y"),
            "endtime": end_date_time.strftime("%H.%M"),
            "enddate": end_date_time.strftime("%d.%m.%y"),
            "actHoliday": "1",
        })

    async def set_holiday_async(self, start_date_time, end_date_time):
        """Set a holiday asynchronously."""
        async with self._lock:
            return await self.hass.async_add_executor_job(
                self.set_holiday, start_date_time, end_date_time
            )

    def set_home(self, home_away):
        """Set home ("0") or away ("2") mode."""
        start_date_time = datetime.now()
        self._post("holiday.htm", {
            "rdbkck": "0",
            "starttime": start_date_time.strftime("%H.%M"),
            "startdate": start_date_time.strftime("%d.%m.%y"),
            "endtime": start_date_time.strftime("%H.%M"),
            "enddate": start_date_time.strftime("%d.%m.%y"),
            "actHoliday": home_away,
        })

    async def set_home_async(self):
        """Set home mode asynchronously."""
        async with self._lock:
            return await self.hass.async_add_executor_job(self.set_home, "0")

    async def set_away_async(self):
        """Set away mode asynchronously."""
        async with self._lock:
            return await self.hass.async_add_executor_job(self.set_home, "2")

    @staticmethod
    def _stat_map(stat_index):
        """Return the NetMonitor's 32-character stat bitmap with one stat set."""
        if not 0 <= stat_index < QUICKSET_SLOTS:
            raise ValueError(f"Stat index {stat_index} is outside the stat map")
        return "".join(
            "1" if slot == stat_index else "0" for slot in range(QUICKSET_SLOTS)
        )

    def boost_heating(self, stat_index, temperature):
        """Boost a stat to a temperature using the quick-set form."""
        data = {
            "rdbkck": "2",
            "quickSet": str(int(round(temperature))),
            "quickSetMap": self._stat_map(stat_index),
            "quickSetGrp": "0",
            "quickSetAct": "1",
        }
        self._send_repeatedly(lambda: self._post("tempset.htm", data))

    async def boost_heating_async(self, stat_index, temperature):
        """Boost heating asynchronously."""
        async with self._lock:
            return await self.hass.async_add_executor_job(
                self.boost_heating, stat_index, temperature
            )

    def hold_temperature(self, stat_index, temperature, hours):
        """Hold a stat at a temperature for a number of hours."""
        data = {
            "rdbkck": "1",
            "tempholdTemp": str(int(round(temperature))),
            "tempholdTime": "{0:02d}".format(int(hours)),
            "tempholdMap": self._stat_map(stat_index),
            "tempholdGrp": "0",
            "tempholdAct": "1",
        }
        self._send_repeatedly(lambda: self._post("temphold.htm", data))

    async def hold_temperature_async(self, stat_index, temperature, hours):
        """Hold a temperature asynchronously."""
        async with self._lock:
            return await self.hass.async_add_executor_job(
                self.hold_temperature, stat_index, temperature, hours
            )

    # frost.htm is deliberately not used for writing. Testing showed its map
    # sets the frost state of every stat at once (1 = frost, 0 = not), so a
    # write re-asserts the NetMonitor's last reading for every room and can
    # override a change made at a thermostat that it hasn't read yet.


    @staticmethod
    def _hidden(content, name):
        """Return the value of a hidden form field on a NetMonitor page."""
        return content.split(name + '" value="')[1].split('"')[0]

    @staticmethod
    def _temperature(text):
        """Convert a two-character temperature, where "NC" means not communicating."""
        return None if text == "NC" else int(text)

    def _parse_quickview(self, content):
        """Parse quickview.htm: six characters per stat position.

        Characters are current temperature (2), target temperature (2),
        heating (1) and hot water (1); stat positions follow statmap.
        """
        statnames = self._hidden(content, "statname").split("#")
        quickvals = self._hidden(content, "quickview")
        statmap = self._hidden(content, "statmap")
        stats = []
        for i, statname in enumerate(statnames):
            if statmap[i : i + 1] != "1":
                continue
            vals = quickvals[i * 6 : i * 6 + 6]
            hw_state = vals[5:6]
            hw_timer_output = STATE_UNAVAILABLE
            if hw_state == "0":
                hw_timer_output = STATE_OFF
            elif hw_state == "1":
                hw_timer_output = STATE_ON
            stats.append(
                HeatmiserStat(
                    i,
                    statname,
                    self._temperature(vals[0:2]),
                    self._temperature(vals[2:4]),
                    HVACMode.HEAT,
                    HVACAction.HEATING if vals[4:5] == "1" else HVACAction.IDLE,
                    hw_timer_output,
                    -1,
                )
            )
        return stats

    def get_devices(self):
        """Get the list of devices."""
        response = self._get("quickview.htm")
        response.raise_for_status()
        return self._parse_quickview(response.content.decode("utf-8"))

    def _get_frost_state(self):
        """Return frost.htm's 32-character map of which stats are in frost mode."""
        response = self._get("frost.htm")
        response.raise_for_status()
        frost_state = self._hidden(response.content.decode("utf-8"), "frostState")
        if len(frost_state) != QUICKSET_SLOTS or set(frost_state) - {"0", "1"}:
            raise ValueError(f"Unexpected frostState {frost_state!r}")
        return frost_state

    def get_all_status(self):
        """Read every stat with two requests: quickview.htm and frost.htm.

        This replaces selecting and reading each stat in turn through
        right.htm, which took one request per stat.
        """
        stats = self.get_devices()
        frost_state = self._get_frost_state()
        for stat in stats:
            if frost_state[stat.id] == "1":
                stat.hvac_mode = HVACMode.OFF
                stat.current_state = HVACAction.OFF
        return {stat.name: stat for stat in stats}

    async def get_all_status_async(self):
        """Read every stat asynchronously."""
        async with self._lock:
            return await self.hass.async_add_executor_job(self.get_all_status)

    def get_comms_stats(self):
        """Read the NetMonitor's per-stat send and receive counters.

        statistics.htm holds four BCD digits per configured stat, in stat
        order, in websendCnt and webrecvCnt; prtmap marks offline stats "!".
        The counters are four digits, so they wrap after 9999.
        """
        quickview = self._get("quickview.htm")
        quickview.raise_for_status()
        content = quickview.content.decode("utf-8")
        statnames = self._hidden(content, "statname").split("#")
        statmap = self._hidden(content, "statmap")

        response = self._get("statistics.htm")
        response.raise_for_status()
        content = response.content.decode("utf-8")
        sent_all = self._hidden(content, "websendCnt")
        received_all = self._hidden(content, "webrecvCnt")
        prtmap = self._hidden(content, "prtmap")

        result = {}
        k = 0
        for i, statname in enumerate(statnames):
            if statmap[i : i + 1] != "1":
                continue
            sent = int(sent_all[k : k + 4])
            received = int(received_all[k : k + 4])
            k += 4
            online = prtmap[i : i + 1] != "!"
            result[statname] = {
                "address": i + 1,
                "sent": sent,
                "received": received,
                "rate": round(100 * received / sent, 1) if sent and online else None,
                "online": online,
            }
        return result

    async def get_comms_stats_async(self):
        """Read the comms counters asynchronously."""
        async with self._lock:
            return await self.hass.async_add_executor_job(self.get_comms_stats)

    async def get_devices_async(self):
        """Get the list of devices asynchronously."""
        async with self._lock:
            return await self.hass.async_add_executor_job(self.get_devices)

    # --- Sending temperature and mode changes ---------------------------------
    # Sends go through right.htm (select the stat, then set it), which only
    # touches that stat; the lock keeps each select-and-set pair together.
    # Each call sends once: the coordinator decides when to resend, by
    # comparing what it wants with what the NetMonitor reads back.

    @staticmethod
    def _setting_data(kind, value):
        if kind == "temperature":
            return {"selSetTemp": "{0:02d}".format(int(value))}
        return {"selFrost": "1" if value == HVACMode.OFF else "0"}

    def _select_and_set(self, name, data):
        """Select a stat on right.htm, then send it one setting, once."""
        self._post("right.htm", {"rdbkck": "1", "curSelStat": name}).raise_for_status()
        self._post("right.htm", data).raise_for_status()

    async def send_setting_async(self, name, kind, value):
        """Send one temperature or mode setting to a stat, once."""
        data = self._setting_data(kind, value)
        async with self._lock:
            await self.hass.async_add_executor_job(self._select_and_set, name, data)

    def get_device_status(self, name) -> HeatmiserStat:
        """Get the device status."""

        response = self._post("right.htm", {"rdbkck": "0", "curSelStat": name})
        if response.status_code == 200:
            content = response.content.decode("utf-8")
            statvals = content.split('statInfo" value="')[1].split('"')[0]
            current_temperature_str = statvals[0:2]
            current_temperature = None
            if current_temperature_str != "NC":
                current_temperature = int(current_temperature_str)
            target_temperature_str = statvals[2:4]
            target_temperature = None
            if target_temperature_str != "NC":
                target_temperature = int(target_temperature_str)
            current_state = statvals[8:9]
            current_mode = statvals[10:11]
            mode = HVACMode.HEAT
            if current_mode == "1":
                mode = HVACMode.OFF
                state = HVACAction.OFF
            else:
                state = HVACAction.IDLE
                if current_state == "1":
                    state = HVACAction.HEATING
                
            hw_timer_output=STATE_UNAVAILABLE
            try:
                current_hw_available = int(statvals[12:13])
                if current_hw_available >2:
                    current_hw_state = statvals[11:12]
                    hw_timer_output=STATE_OFF
                    if current_hw_state =="1":
                        hw_timer_output=STATE_ON
            except(ValueError, TypeError):
                pass

            boostTime=-1
            boostVals = content.split('hwBoost" value="')[1].split('"')[0]
            if boostVals !="ff":
                boostTime=int(boostVals)

            stat = HeatmiserStat(
                0, name, current_temperature, target_temperature, mode, state,hw_timer_output,boostTime
            )
            return stat
        else:
            return None

    # --- Comms testing -------------------------------------------------------
    # These send a setting exactly as many times as asked, with no automatic
    # repeats, and read a stat back without updating the entities, so the
    # behaviour of the NetMonitor and the stat network can be measured.

    def _test_send_once(self, name, method, data):
        """Send one setting once, by the chosen method. Return what happened.

        "select" selects the stat on right.htm, then sends the setting there
        (two requests, as set_temperature and set_mode do). "map" sends one
        request to tempset.htm, naming the stat in the map (temperature only).
        """
        result = {"time": datetime.now().isoformat(timespec="milliseconds")}
        try:
            if method == "select":
                select = self._post("right.htm", {"rdbkck": "1", "curSelStat": name})
                result["select_status"] = select.status_code
                if select.status_code == 200:
                    send = self._post("right.htm", data)
                    result["send_status"] = send.status_code
            else:
                send = self._post("tempset.htm", data)
                result["send_status"] = send.status_code
        except requests.RequestException as err:
            result["error"] = str(err)
        result["done"] = datetime.now().isoformat(timespec="milliseconds")
        return result

    def _test_data(self, stat_index, method, temperature, hvac_mode):
        """Build the form data for a test send."""
        if method == "select":
            if temperature is not None:
                return {"selSetTemp": "{0:02d}".format(int(temperature))}
            return {"selFrost": "1" if hvac_mode == HVACMode.OFF else "0"}
        if temperature is None:
            # frost.htm sets every stat's frost state, so modes are select-only.
            raise ValueError("Modes can only be test-sent with method select")
        return {
            "rdbkck": "2",
            "quickSet": "{0:02d}".format(int(temperature)),
            "quickSetMap": self._stat_map(stat_index),
            "quickSetGrp": "0",
            "quickSetAct": "1",
        }

    async def test_send_async(
        self, name, stat_index, method, temperature, hvac_mode, attempts, gap
    ):
        """Send a setting a fixed number of times, gap seconds apart.

        The lock is released between attempts so polls can run in the gaps.
        """
        async with self._lock:
            data = await self.hass.async_add_executor_job(
                self._test_data, stat_index, method, temperature, hvac_mode
            )
        results = []
        for attempt in range(attempts):
            if attempt and gap:
                await asyncio.sleep(gap)
            async with self._lock:
                outcome = await self.hass.async_add_executor_job(
                    self._test_send_once, name, method, data
                )
            outcome["attempt"] = attempt + 1
            _LOGGER.info(
                "test_send %s %s %s attempt %d: %s", name, method, data, attempt + 1, outcome
            )
            results.append(outcome)
        return {"method": method, "sent": data, "attempts": results}

    def _test_poll(self, name):
        """Read one stat straight from the NetMonitor, including the raw values."""
        result = {"time": datetime.now().isoformat(timespec="milliseconds")}
        try:
            response = self._post("right.htm", {"rdbkck": "0", "curSelStat": name})
            result["status"] = response.status_code
            content = response.content.decode("utf-8")
            statvals = content.split('statInfo" value="')[1].split('"')[0]
            result["raw"] = statvals
            result["current_temperature"] = statvals[0:2]
            result["target_temperature"] = statvals[2:4]
            result["heating"] = statvals[8:9] == "1"
            result["hvac_mode"] = "off" if statvals[10:11] == "1" else "heat"
        except (requests.RequestException, IndexError, ValueError) as err:
            result["error"] = str(err)
        result["done"] = datetime.now().isoformat(timespec="milliseconds")
        return result

    def _test_poll_bulk(self, name):
        """Read one stat from the bulk pages (quickview.htm and frost.htm)."""
        result = {"time": datetime.now().isoformat(timespec="milliseconds")}
        try:
            stat = self.get_all_status().get(name)
            if stat is None:
                result["error"] = f"{name} isn't in the NetMonitor's stat list"
            else:
                result["current_temperature"] = stat.current_temperature
                result["target_temperature"] = stat.target_temperature
                result["heating"] = stat.current_state == HVACAction.HEATING
                result["hvac_mode"] = str(stat.hvac_mode)
        except (requests.RequestException, IndexError, ValueError) as err:
            result["error"] = str(err)
        result["done"] = datetime.now().isoformat(timespec="milliseconds")
        return result

    async def test_poll_async(self, name, method="select"):
        """Read one stat straight from the NetMonitor."""
        func = self._test_poll if method == "select" else self._test_poll_bulk
        async with self._lock:
            result = await self.hass.async_add_executor_job(func, name)
        result["method"] = method
        _LOGGER.info("test_poll %s: %s", name, result)
        return result

    async def get_device_status_async(self, name) -> HeatmiserStat:
        """Get the device status asynchronously."""
        async with self._lock:
            return await self.hass.async_add_executor_job(
                self.get_device_status, name
            )
