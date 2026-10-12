# KeepLink Managed Switch for Home Assistant

Local-polling integration for **KeepLink KP-9000 series** managed switches (and, very likely, other
Realtek-based switches that share the same web interface, such as some Horaco models). It talks to the
switch's built-in web interface: no cloud, no SNMP, nothing to install on the switch.

Tested on:

| Model | Firmware | Notes |
|---|---|---|
| KP-9000-9XHPML-X-AC | V100.9.4 | 8 × 2.5G PoE+ ports, 1 × 10G SFP+ |
| KP-9000-9XHML-X | V100.9.5 | 8 × 2.5G ports, 1 × 10G SFP+ (no PoE) |

## Features

- **Per port:** link up/down, negotiated speed ("Down", "100 Mbit/s", "2.5 Gbit/s", "10 Gbit/s", "Disabled"),
  configured speed, flow control, PVID, and the number of MAC addresses learned.
- **Port descriptions** that you set in Home Assistant (the switch cannot store them). They appear in entity names
  and as an attribute.
- **PoE (PoE models):** per-port on/off switch, power (W), voltage, current, class, and the switch's total PoE power.
  Power readings were checked against a UPS power monitor and are repeatable; the wall draw is roughly 20% above
  what the ports report because of conversion losses.
- **Port enable/disable switch** (disabled by default) for the port's administrative state.
- **Device tracker for wired devices**, built from the switch's MAC address table (like UniFi's wireless
  tracker, but for ports). Ports that carry many devices (uplinks, access points, other switches) can be
  ignored.
- **Buttons:** reboot, and save configuration.
- Optional **auto-save** after every change made from Home Assistant.
- Reauthentication, reconfiguration and diagnostics support.

## Installation

### HACS (custom repository)

1. HACS → ⋮ → *Custom repositories* → add `https://github.com/scottbambrick/ha-keeplink-switch`, type *Integration*.
2. Install **KeepLink Managed Switch** and restart Home Assistant.
3. *Settings → Devices & services → Add integration → KeepLink Managed Switch*.

### Manual

Copy `custom_components/keeplink_switch` into your Home Assistant `custom_components` folder and restart.

## Setup

Enter the switch's IP address and its web login (the default on these switches is `admin` / `admin`).
PoE support is detected from the model name; you can override it in the options.

### Options

| Option | |
|---|---|
| Poll interval | 10–600 s (default 30). A poll takes 1–2 s. |
| Save after each change | Writes the configuration to flash after PoE/port changes (default on). |
| This switch has PoE | Override the automatic detection. |
| Track wired devices | Create a `device_tracker` per MAC address seen on a non-ignored port. |
| Ports ignored for device tracking | Uplinks, access-point ports and links to other switches. |
| Port descriptions | Free text per port. |

## Things you should know

- **The switch allows one web session at a time.** Logging in from a browser signs Home Assistant out and
  vice versa. Home Assistant logs back in on its next poll.
- **Unsaved changes are lost when the switch reboots.** This is how the firmware works (verified by rebooting).
  Leave *Save after each change* on, or use the *Save configuration* button.
- **The switch only exposes packet counters, not byte counters**, so this integration does not provide traffic
  sensors. (The web interface's "Port Statistics" page counts packets.)
- Turning off the port that Home Assistant (or your uplink) uses will cut you off from the switch. That is why
  the port enable/disable switch is disabled by default.
- Device tracking sees every MAC learned on a port. A Wi-Fi access point's clients therefore appear as
  "wired" devices on its port: add that port to the ignore list.

## Using PoE power in the Energy dashboard

Create a Riemann sum helper (*Settings → Helpers → Integration*) on a port's *PoE power* sensor with a
maximum sub-interval of 1 minute, then add it as an individual device in *Settings → Dashboards → Energy*.
If the switch sits behind a metered device, nest it under that device with *included in stat* so it is
split out rather than counted twice.

## Credits

The login scheme and CGI endpoints were worked out from the switch's own web interface. Prior art for
Horaco/KeepLink switches: [gtrancillo/horaco_switch_ha](https://github.com/gtrancillo/horaco_switch_ha) and
[byte4geek/switch-dashboard](https://github.com/byte4geek/switch-dashboard).

## License

MIT
