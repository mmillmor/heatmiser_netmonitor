# Heatmiser Netmonitor
Integrate a Heatmiser Netmonitor heating system with Home Assistant.
This integration offers thermostat and hot water control. It also has the following services;

1. Hot water boost - this will boost the hot water for the number of hours you specify (0 cancels)
1. Boost heating - this will boost a thermostat to the temperature you specify
1. Hold temperature - this will hold a thermostat at a temperature for the number of hours you specify
1. Setback heating - this will set a thermostat back
1. Set time - this will set the system time to the current time. Note, you must call this for one entity, but it will update the whole system when you do
1. Set Holiday - this allows you to set and unset a holiday
1. Set Home - set mode to Home
1. Set Away - set mode to Away

## Service examples

### Set away when you leave a zone

To set the system to Away status when you leave a zone, create an automation of type "Create new automation", with a trigger of Time and location -> Zone, and an action of Heatmiser NetMonitor 'Set Away'

![image](https://github.com/user-attachments/assets/00bbd606-2eb0-44d7-b7b7-b67973a84aa1)

The yaml for this looks like;

```
description: ""
mode: single
triggers:
  - trigger: zone
    entity_id: device_tracker.pixel_7_2
    zone: zone.home
    event: leave
conditions: []
actions:
  - action: heatmiser_netmonitor.set_away
    metadata: {}
    data: {}
    target:
      entity_id: climate.bedroom
```

### Set Away when you press a button

To add a toggle to the home page which switches between home and away, first of all add a Helper toggle under Devices -> Helpers

![image](https://github.com/user-attachments/assets/bb7b4c17-db33-4de3-bf36-8de108c51b2d)

Next, add an automation based on the toggle state, which is called whenever the state changes. Add a conditional action which sets the state to Home if on, and Away if off 

![image](https://github.com/user-attachments/assets/ffb9e6ce-bedc-44df-91be-71ce75fc7c85)

the yaml for this looks like;

```
alias: Heating Home/Away
description: ""
triggers:
  - trigger: state
    entity_id:
      - input_boolean.home_away
conditions: []
actions:
  - choose:
      - conditions:
          - condition: state
            entity_id: input_boolean.home_away
            state: "on"
        sequence:
          - action: heatmiser_netmonitor.set_home
            metadata: {}
            data: {}
            target:
              entity_id: climate.bedroom
      - conditions:
          - condition: state
            entity_id: input_boolean.home_away
            state: "off"
        sequence:
          - action: heatmiser_netmonitor.set_away
            metadata: {}
            data: {}
            target:
              entity_id: climate.bedroom
mode: single
```

## Comms reliability

The NetMonitor talks to the thermostats over an RS485 network, and on some
installations messages are lost. The integration helps in a few ways:

- **Polling** reads every thermostat with two requests (`quickview.htm` and
  `frost.htm`) instead of selecting and reading each one in turn, so it adds
  less traffic to the network.
- **Comms success sensors**: each thermostat has a diagnostic sensor showing
  the share of the NetMonitor's messages to it that got a reply, read from
  `statistics.htm` every 5 minutes. The raw send and receive counts are
  attributes. The NetMonitor's counters are four digits, so they wrap after
  9999.
- **Errors**: when the NetMonitor can't be reached, actions fail with a normal
  Home Assistant error, so `continue_on_error` in automations can skip them.

### How the NetMonitor behaves

Testing on a real system showed:

- A single change sent to a thermostat rarely sticks. The NetMonitor shows the
  new value straight away, then its own read of the thermostat 25-60 seconds
  later puts the old value back. Sending it several times over 30-45 seconds
  makes it stick.

### How changes are delivered

For each thermostat setting Home Assistant changes, the integration keeps the
value the thermostat is known to have (current) and the value wanted (target),
and checks them on every 30-second poll:

- A change is sent straight away and then every 15 seconds, four times in all,
  on its own timer. In testing, changes stuck reliably when several sends were
  spread over 30-45 seconds, while two sends were hit and miss.
- A reading only counts as the thermostat's real value 90 seconds after the
  last send, because until then the NetMonitor may just be showing what was
  sent. If it then matches the target, the change is confirmed; if it has gone
  back, another round starts, up to 3 rounds, after which the integration
  logs an error and accepts what the thermostat reports.
- If a reading is neither the old nor the new value, or a confirmed setting
  later changes, someone changed it at the thermostat (or its program did),
  and that change wins.

Changes go through `right.htm` (select the thermostat, then set it), which
only touches that thermostat. Resends happen on polls, so keep polling enabled.
- `frost.htm` sets the frost state of **every** thermostat at once (1 = frost,
  0 = not), so writing it re-asserts the NetMonitor's last reading for every
  room, and can override a change made at a thermostat that the NetMonitor
  hasn't read yet. The integration only reads `frost.htm`; `setback_heating`
  puts the one thermostat into frost the same way as `set_hvac_mode: off`.

### Test actions

For investigating reliability, `heatmiser_netmonitor.test_send` sends one
temperature or mode exactly as many times as you ask, with a chosen gap, and
`heatmiser_netmonitor.test_poll` reads one thermostat straight from the
NetMonitor without updating its entity. Both return what happened as response
data. Turning off polling for the integration (System options) while testing
keeps other traffic off the network.
