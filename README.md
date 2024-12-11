# Heatmiser Netmonitor
Integrate a Heatmiser Netmonitor heating system with Home Assistant.
This integration offers thermostat and hot water control. It also has the following services;

1. Hot water boost - this will boost the hot water for the specified time
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
