# Delivering changes to Heatmiser stats: what the code must do

## How the NetMonitor behaves (measured)
- HA talks to a Heatmiser NetMonitor over HTTP; the NetMonitor talks to up to 32 thermostats ("stats") over a noisy RS-485 bus.
- A write (right.htm: select the stat, then send selSetTemp or selFrost) changes the NetMonitor's copy at once. The next read shows the new value even if the stat never got it.
- The NetMonitor reads each stat on its own cycle. If the write didn't reach the stat, the old value comes back on that read, 25–60 s after the write.
- So a reading only proves the stat has a value once about 60–90 s have passed since the last write.
- A single write rarely sticks. Bursts of several writes usually do, but no pattern is guaranteed: 10 sends 1 s apart, 4 sends 15 s apart and 5 sends 2 s apart have each worked and have each failed at times.
- Someone can also change a stat at the thermostat itself, or its own program can change it. HA should accept such changes, not fight them.
- HA polls all stats every 30 s (quickview.htm and frost.htm).

## Requirements
1. When the user or an automation sets a temperature or a mode (heat/frost), the HA UI shows the requested value immediately and keeps showing it until the change is confirmed or given up on.
2. The change is sent as a burst (SENDS_PER_ROUND sends, RESEND_EVERY s apart).
3. Once SETTLE_AFTER s have passed since the last send, a reading equal to the request confirms it. A reading still at an old value means the change failed: send another burst, up to MAX_ROUNDS, then give up, log an error, and show the reading.
4. A new request for the same stat and setting replaces any request in flight, at any point, including a request back to the original value. Repeated fast toggling must end with the last request delivered, and the UI must never bounce to an older value.
5. A reading that HA never sent and that isn't the last confirmed value is a change made outside HA. It wins: adopt it and stop sending.
6. With nothing in flight, a reading that differs from the last known value is likewise an outside change; adopt it.
7. Temperature and mode are tracked independently. Each stat is independent. Several stats may be changing at once (automations switch several rooms together); sends go through one lock.
8. A send failing with a network error must not lose the request; later polls retry it.
9. NetMonitor sessions can expire (writes then fail silently). That is out of scope beyond requirement 3's retries.
