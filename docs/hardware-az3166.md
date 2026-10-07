<!-- Made with Claude (Claude Code, Anthropic) -->
# AZ3166 hardware node: sensor telemetry over MQTT

This section covers the working hardware node built on the **MXChip AZ3166 IoT DevKit**, running **Eclipse ThreadX / NetX Duo**. The board reads its onboard sensors, shows them on its OLED screen, and publishes them to an MQTT broker so any laptop on the hackathon network can pull live readings without touching the hardware.

Code lives under [`MXChip/AZ3166`](../MXChip/AZ3166) and is based on [eclipse-threadx/samplex](https://github.com/eclipse-threadx/samplex). See [`MXChip/AZ3166/README.md`](../MXChip/AZ3166/README.md) for the original toolchain/cloning instructions (ARM GCC, CMake, Ninja, submodules).

## What's in `MXChip/AZ3166`

- **`starter` app** — connects to Wi-Fi, reads the four onboard sensors (temperature/humidity, pressure, accelerometer, magnetometer) every 2 seconds, prints them over the serial console (115200 baud) and renders them in a small 6x8 font on the OLED screen.
- **`mqtt` app** — same sensors, but it follows the RoM sensor contract (`libs/rom-common/rom_common/contracts.py`): every 500 ms it publishes a JSON message with the temperature on `rom/sensor/battery/temp` (QoS 0), and it keeps `rom/sensor/battery/status` (`online` / `offline`, QoS 1, retained; `offline` is the MQTT Last Will) up to date. Publishing anything to the board's `ThreadXAZ3166/incoming` topic still triggers an immediate extra message. This is the one running for the hackathon demo.
  - **Guardian state on the OLED:** it subscribes to `rom/actuator/display/cmd` (QoS 1, retained; published by `services/guardian`) and shows state, `temp_c` and reason on the lower three lines. Invalid commands are ignored, and with no command for 5 seconds it shows `G:NO LINK`.
  - **Reconnects by itself:** if the broker goes away the board keeps retrying (1, 2, 4, 8, then every 10 s), and on reconnect it restores the Last Will, publishes `online` again and re-subscribes, so telemetry and the display resume without a reset.
- Two small fixes worth knowing about if you touch this code:
  - `ssd1306_conf.h`: enabled the `Font_6x8` tiny font (it ships disabled) so four sensor lines fit on the 128x64 OLED at once.
  - Standard `printf`/`snprintf` on this target are built without float support (newlib-nano). Any `%f` formatting must go through nanoprintf's own `npf_snprintf` (`#include "nanoprintf.h"`) instead — see `app/starter/main.c` and `app/mqtt/telemetry.c`.

## Building and flashing

```bash
cd MXChip/AZ3166
git submodule update --init   # fetches threadx + netxduo if you haven't already
bash scripts/build.sh starter   # or: bash scripts/build.sh mqtt
```

Wi-Fi credentials are never committed. For the `mqtt` app, create a git-ignored `MXChip/AZ3166/app/mqtt/cloud_config_local.h` next to `cloud_config.h` with your own values:

```c
#define WIFI_SSID     "your-ssid"
#define WIFI_PASSWORD "your-password"
```

Also set the IP of your broker (`MQTT_LOCAL_BROKER_IP`) in `cloud_config.h` (use your laptop's LAN IP; do not commit environment-specific values). For the `starter` app, fill in `app/starter/cloud_config.h` locally and do not commit it.

The ThreadX / NetX Duo submodules are pinned to known-working revisions (newer 6.5.x-era revisions fail DHCP with this WICED stack). Do not update them.

Flashing is drag-and-drop: the board mounts as a USB mass storage drive. Copy the built binary onto it:

```bash
cp build/app/mxchip_threadx.bin /media/<you>/AZ3166/
```

The board resets and runs the new firmware automatically. Note: after a flash, the drive sometimes remounts read-only (the host sees the mid-flash USB disconnect as an I/O error). Remount it before copying again:

```bash
udisksctl unmount -b /dev/sda && udisksctl mount -b /dev/sda
```

Serial console (boot log, sensor prints): `/dev/ttyACM0` (or the equivalent serial port on your OS) at 115200 baud, e.g. `screen /dev/ttyACM0 115200`.

## Setting up the MQTT broker

Any Mosquitto broker on the hackathon LAN works. Example on Linux:

```bash
sudo tee /etc/mosquitto/conf.d/hackathon.conf > /dev/null <<'CONF'
listener 1883 0.0.0.0
allow_anonymous true
CONF
sudo systemctl restart mosquitto
```

This opens the broker to every device on the network with no authentication — fine for a short-lived hackathon LAN, not for anything you'd leave running afterwards.

## Pulling sensor data from your own laptop

Once the `mqtt` app is flashed and connected, anyone on the same Wi-Fi can read live sensor data — no cables, no pairing.

**Connection details** (adjust the host to whatever the broker's actual LAN IP is):

| | |
|---|---|
| Broker host | `<broker-lan-ip>` |
| Port | `1883` (no auth) |
| Sensor topic | `rom/sensor/battery/temp` (QoS 0) |
| Status topic | `rom/sensor/battery/status` (QoS 1, retained: `online` / `offline`) |
| Request topic | `ThreadXAZ3166/incoming` (optional, on demand) |

**1. Install an MQTT client**

| OS | Command |
|---|---|
| macOS | `brew install mosquitto` |
| Linux / WSL | `sudo apt install mosquitto-clients` |
| Windows | `winget install EclipseMosquitto` |

**2. Watch the live feed** — prints a new message every 500 ms:

```bash
mosquitto_sub -h <broker-lan-ip> -t "rom/sensor/battery/#" -v
```

Example output:

```
rom/sensor/battery/status online
rom/sensor/battery/temp {"device_id":"az3166-01","seq":64,"ts_ms":1791305613274,"temp_c":28.75}
rom/sensor/battery/temp {"device_id":"az3166-01","seq":65,"ts_ms":1791305613794,"temp_c":28.75}
```

`seq` starts at 1 after every boot; `ts_ms` is epoch milliseconds once the board has synced time over SNTP (uptime milliseconds before that, which the adapter treats as "no latency info"); `temp_c` is the board's onboard temperature sensor, standing in for the battery temperature. If the board drops off the network the broker publishes the retained `offline` status within about 15 seconds.

**3. Ask for an extra message on demand** — publish anything to the request topic and the board sends one more message immediately, instead of waiting for the next 500 ms tick:

```bash
mosquitto_pub -h <broker-lan-ip> -t "ThreadXAZ3166/incoming" -m "get"
```

**4. Prefer a GUI?** Install [MQTT Explorer](https://mqtt-explorer.com), add a connection with the broker host above, port `1883`, no credentials, then expand the `rom/sensor/battery` topic tree. Readings update live as a tree view — no commands needed.

**If nothing comes through:** confirm you're on the same Wi-Fi as the broker (both the 2.4GHz and 5GHz bands of the same AP usually reach it) and that the host IP above is still current — if the broker runs on someone's laptop, a DHCP lease change will move it.
