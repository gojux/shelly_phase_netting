# Shelly Phase Netting for Home Assistant

🇩🇪 [Deutsche Version](README.de.md)

This custom integration reads `EMData.GetData` from a Shelly Pro 3EM, nets every stored minute across all three phases and provides two counters that work with the Home Assistant Energy dashboard:

- Netted grid import (kWh)
- Netted grid export (kWh)

In addition there is a diagnostic sensor "Last processed record" (timestamp; it is listed under "Diagnostic" on the device page). Its `cursor` attribute holds the position from which the next poll continues reading.

The cursor and both totals are persisted in Home Assistant after every successful data import. If Home Assistant is down for a while, the gap is filled from the Shelly's history afterwards. Nothing is ever written to the Shelly.

Note: "netting" here means summing import and export across the phases per minute (what German meters call *saldierende Messung*). It is not the utility billing scheme also called "net metering".

## Why this integration?

**The problem:** The energy counters (kWh) of the Shelly Pro 3EM add up import and return *per phase*. If, for example, a balcony power plant feeds in on one phase while another phase draws power, both counters run at the same time, and the totals exceed what your utility meter records, because that meter nets the phases. Only the instantaneous total power (`total_act_power`) is netted.

**Existing approaches** and where they fall short:

| Approach | How it works | Drawbacks |
|---|---|---|
| [Home Assistant template sensors + integral helpers](https://www.simon42.com/shelly-pro-3em-saldierung-home-assistant/) | Split the total power into an import and an export sensor and integrate both over time. | Only samples of the power are integrated, so accuracy depends on how often the Shelly reports. While Home Assistant is down or restarting nothing accumulates, and the gap cannot be filled in afterwards. No history before the helpers were created. Two template sensors and two helpers have to be set up and maintained by hand. |
| [Script on the Shelly](https://github.com/chackl1990/shelly-pro-3em-net-metering) or [with MQTT](https://gist.github.com/Davc0m/dc419aa3147ec3c3d6e7289f89dc0ed8) | An mJS script on the device integrates the power every 500 ms and keeps the counters on the device. | Changes the device: a script has to be installed and kept working across firmware updates (one project is only tested on firmware 1.7.1). The counters are stored on the device, which means regular flash writes (one author estimates a lifetime of about 5 years with a write every 15 minutes). Some variants require MQTT. |

**What this integration does differently:**

- **It uses the energy the Shelly has already recorded.** The Pro 3EM stores per-phase energy in one-minute records. The integration reads these records (`EMData.GetData`) and nets each minute across the phases, instead of integrating sampled power.
- **Outages of Home Assistant or the network do not create gaps.** The read position (cursor) and the totals are persisted. When Home Assistant is reachable again, it continues exactly where it stopped and catches up from the Shelly's history (the Shelly keeps about 60 days). Restarts, updates and network problems therefore do not lose energy.
- **History from day one.** On setup the counters can be filled from up to 45 days of Shelly history, so they do not start at zero, and the hourly history is written to the long-term statistics, so the Energy dashboard shows it as well (see below).
- **The Shelly is left untouched.** The integration only reads: no script, no MQTT, no configuration change, and therefore no additional flash wear and no dependency on a specific firmware version.
- **Ready to use.** Two energy sensors that work with the Energy dashboard, with re-authentication and a configuration dialog, instead of hand-built helpers.

**Trade-offs:**

- Netting is done per stored minute. Opposite power flows within the same minute can cancel each other out, while a script that nets at 500 ms follows short-term changes more closely.
- The values follow the Shelly's records with a delay of up to one polling interval (60 seconds by default) plus the few seconds the Shelly needs to store a finished minute. This integration does not provide live power; use the native Shelly integration for that.
- After an outage the missing energy is added as soon as Home Assistant can reach the Shelly again. The totals are correct, but the Energy dashboard books the increase at the time of catching up, not in the hours in which the energy was actually used.
- Only devices with the `EMData` component (Pro 3EM in triphase profile) are supported.

## Installation

### Via HACS (recommended)

[![Open your Home Assistant instance and open this repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=gojux&repository=shelly_phase_netting&category=integration)

1. Click the button above (or in HACS: ⋮ → **Custom repositories** → add `https://github.com/gojux/shelly_phase_netting` as category **Integration**).
2. Download **Shelly Phase Netting** in HACS and restart Home Assistant.

### Manually

Copy the folder `custom_components/shelly_phase_netting` to `/config/custom_components/` and restart Home Assistant.

## Setup

1. Open **Settings → Devices & services → Add integration → Shelly Phase Netting**.
2. Enter the IP address or hostname of the Pro 3EM. If Shelly authentication is enabled, also enter the password (the user name is always `admin` on Shelly Gen2). Authentication uses SHA-256 digest.
3. Choose how far back to import (default: 24 hours, at most 45 days).
4. Once the import has finished, select the two kWh sensors in the Energy dashboard as grid consumption and return to grid.

## How the calculation works

The Pro 3EM stores one record per minute. Each record contains, for every phase (A, B, C), the energy that was **consumed** and the energy that was **returned** during that minute in Wh. For every record the integration does the following:

```
net = (A_consumed − A_returned) + (B_consumed − B_returned) + (C_consumed − C_returned)

net ≥ 0  →  import total += net
net < 0  →  export total += −net
```

Example with three minutes (all values in Wh):

| Minute | A | B | C | Net | Import total | Export total |
|---|---|---|---|---|---|---|
| 1 | 10 consumed | 4 returned | – | +6 | 6 | 0 |
| 2 | 2 consumed | 5 returned | 1 consumed | −2 | 6 | 2 |
| 3 | 3 consumed | – | – | +3 | 9 | 2 |

The netted totals are 9 Wh import and 2 Wh export. The Shelly's own per-phase counters would show 16 Wh consumed and 9 Wh returned for the same three minutes.

How the records are processed:

- **Only finished minutes are counted.** The Pro 3EM does not deliver the minute that is still running: a minute appeared within a few seconds after its end (observed on a Pro 3EM). The integration therefore never books partial values.
- **Every record is counted exactly once.** The integration keeps a read position (cursor) that points to the end of the last processed record. Each poll asks the Shelly for the records from the cursor on (`EMData.GetData`) and follows its paging (`next_record_ts`) until everything is read.
- **The state is saved after every poll that made progress:** both totals in Wh, the cursor and the time of the last record. After a restart of Home Assistant the integration continues from there.
- **A failed poll changes nothing.** If the Shelly cannot be reached, or the answer is incomplete, neither the totals nor the cursor are touched. The next successful poll reads the same records again, so nothing is lost and nothing is counted twice.
- **First start:** the cursor is set to the chosen backfill point in time (rounded down to a full minute), and the records from then on are processed like any others. Large backlogs are read in stages of at most 20 pages per poll, with follow-up polls every 2 seconds.
- **Gaps in the Shelly's history** (for example while the Shelly was off) are skipped: the cursor jumps to the next stored record.
- **History for the Energy dashboard:** During the initial backfill the energy is also summed per hour. Once the backfill is complete, these hourly values are written to the recorder's long-term statistics of the two energy sensors, ending with the last full hour before the current one; Home Assistant compiles the rest from the live values. So that its own running sum continues exactly where the imported one ends, one 5-minute statistics row is imported as the starting point for it; without it the sum would jump back by the imported total. The first hour only serves as the baseline. This happens once, on the initial setup only, and only if the recorder has no statistics for the sensors yet (otherwise existing values would be overwritten; a warning is logged). To get the history for an existing installation, remove the integration, delete the leftover statistics of both sensors (Developer tools → Statistics) and set the integration up again. The sensor's own state history only begins at the moment of setup; before that, the history panel shows the imported hourly values as steps. Outages later on are booked when they are caught up (see above).
- **Output:** the sensors show the totals in kWh (Wh ÷ 1000, up to six decimals) and are of the type `total_increasing`, which is what the Energy dashboard expects.

## Behaviour and limitations

- The Pro 3EM must run in the **triphase profile** (3 phases). The monophase profile has no `EMData` component (it uses `EM1Data` instead); setup reports a corresponding error in that case.
- The counters start at the chosen backfill point in time, not at the historical meter reading of your grid operator.
- Netting is done per stored 60-second interval. Short-term consumption and feed-in within the same minute can therefore cancel each other out.
- The backfill runs in stages (at most 20 pages per poll, follow-up polls every 2 seconds) and does not block the setup. The two energy sensors stay `unavailable` until the backfill is complete and its history has been imported, so the first value they report is the complete total and the Energy dashboard does not book the backfilled energy as consumption in the first hour. The `catch_up_pending` attribute of the diagnostic sensor shows whether catching up is still in progress.
- Data that has already dropped out of the Shelly's internal history cannot be recovered.
- The polling interval (30–3600 seconds, default 60) can be changed in the integration options; the integration reloads automatically when you do.
- If the Shelly rejects the credentials (for example after a password change), Home Assistant starts a re-authentication dialog.
- If the Shelly gets a new IP address or hostname, change it under **Settings → Devices & services → Shelly Phase Netting → ⋮ → Reconfigure**. It must be the same device (checked by its MAC address); an empty password field keeps the stored password. The read position and totals are kept.
- Back up your Home Assistant data before deleting or re-adding the integration: removing the config entry also deletes its stored cursor and totals (`.storage/shelly_phase_netting.<entry_id>`); a newly added entry starts at 0 again.

## Tests

The tests run in Docker against different Python and Home Assistant versions (no local Python setup needed):

```bash
docker compose run --rm tests        # latest Python + latest Home Assistant
docker compose run --rm tests-min    # oldest supported Home Assistant (see hacs.json)
docker compose run --rm tests-beta   # latest Home Assistant pre-release
```

Any combination and extra pytest arguments work too, for example:

```bash
PYTHON_VERSION=3.14 HA_VERSION=2026.3.0 docker compose run --rm tests -k reauth -x
```

Without Docker: `pip install -r requirements_test.txt && pytest`.

## License

[MIT](LICENSE) © gojux
