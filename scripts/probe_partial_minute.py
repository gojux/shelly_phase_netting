#!/usr/bin/env python3
"""Find out how a Shelly Pro 3EM treats the minute that is still in progress.

Polls EMData.GetData repeatedly (crossing at least one minute boundary) and reports
  * whether the running minute is already delivered,
  * whether the values of a record change after it was first seen (partial data),
  * how long after its end a finished minute becomes available.

Usage: probe_partial_minute.py HOST [--password PW] [--interval 5] [--duration 150]
Requires only the `requests` package. The Shelly must have a valid time (NTP).
"""
from __future__ import annotations

import argparse
import sys
import time

import requests
from requests.auth import HTTPDigestAuth

KEYS = (
    "a_total_act_energy", "a_total_act_ret_energy",
    "b_total_act_energy", "b_total_act_ret_energy",
    "c_total_act_energy", "c_total_act_ret_energy",
)


def rpc(session: requests.Session, host: str, method: str, **params) -> dict:
    response = session.get(f"http://{host}/rpc/{method}", params=params, timeout=10)
    response.raise_for_status()
    return response.json()


def shelly_now(session: requests.Session, host: str) -> float:
    """Current Shelly time; accurate to about +-1 s because unixtime is an integer."""
    started = time.time()
    unixtime = rpc(session, host, "Sys.GetStatus")["unixtime"]
    if unixtime is None:
        sys.exit("The Shelly has no valid time (NTP not synchronised).")
    return unixtime + 0.5 + (time.time() - started) / 2


def fetch_records(session: requests.Session, host: str, since: int) -> dict[int, tuple]:
    """Return {record start ts: (period, (act_sum_wh, ret_sum_wh))} for records >= since."""
    records: dict[int, tuple] = {}
    ts: int | None = since
    for _ in range(10):
        payload = rpc(session, host, "EMData.GetData", id=0, ts=ts)
        idx = [payload["keys"].index(key) for key in KEYS]
        for block in payload.get("data", []):
            for n, row in enumerate(block["values"]):
                values = [row[i] for i in idx]
                records[block["ts"] + n * block["period"]] = (
                    block["period"], (round(sum(values[0::2]), 3), round(sum(values[1::2]), 3))
                )
        ts = payload.get("next_record_ts")
        if ts is None:
            break
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("host")
    parser.add_argument("--password", help="Shelly password (user name is always admin)")
    parser.add_argument("--interval", type=float, default=5, help="seconds between polls")
    parser.add_argument("--duration", type=float, default=150, help="total run time in seconds")
    args = parser.parse_args()

    session = requests.Session()
    if args.password:
        session.auth = HTTPDigestAuth("admin", args.password)

    first_seen: dict[int, float] = {}     # record ts -> Shelly time of first sighting
    versions: dict[int, list] = {}        # record ts -> [(Shelly time, values), ...] on change
    baseline: set[int] = set()            # records already present at the first poll
    deadline = time.time() + args.duration
    poll = 0
    print("poll  sec-in-minute  newest-record-age  records")
    while True:
        try:
            now = shelly_now(session, args.host)
            records = fetch_records(session, args.host, int(now) - 180)
        except requests.HTTPError as err:
            sys.exit(f"HTTP error: {err} (wrong password?)")
        except requests.RequestException as err:
            sys.exit(f"Shelly not reachable: {err}")
        for ts, (period, values) in records.items():
            first_seen.setdefault(ts, now)
            if poll == 0:
                baseline.add(ts)
            history = versions.setdefault(ts, [])
            if not history or history[-1][1] != values:
                history.append((now, values))
        newest = max(records)
        print(f"{poll:4d}  {now % 60:13.1f}  {now - newest:16.1f}s  {len(records):7d}")
        poll += 1
        if time.time() + args.interval > deadline:
            break
        time.sleep(args.interval)

    early = [ts for ts in first_seen if first_seen[ts] < ts + 60]
    changed_early = [ts for ts in early if len(versions[ts]) > 1]
    lags = [first_seen[ts] - (ts + 60) for ts in first_seen if ts not in baseline and ts not in early]

    print("\n--- Result ---")
    if early:
        print(f"The running minute IS delivered ({len(early)} record(s) seen before their period ended).")
        if changed_early:
            print("Its values change while the minute runs -> partial data. Example:")
            ts = changed_early[0]
            shown = versions[ts] if len(versions[ts]) <= 4 else versions[ts][:3] + versions[ts][-1:]
            for seen_at, (act, ret) in shown:
                print(f"  record {ts}: at {seen_at - ts:5.1f}s into the minute act={act} Wh ret={ret} Wh")
            print(f"  ({len(versions[ts])} different values seen in total)")
            print("An integration that advances its cursor past such a record loses the rest of the minute.")
        else:
            print("Its values did not change between polls (final or constant).")
    else:
        print("The running minute is NOT delivered; only finished minutes appear.")
        if lags:
            print(f"A finished minute became visible {min(lags):.1f}-{max(lags):.1f}s after its end "
                  f"(accuracy about the poll interval of {args.interval:g}s).")
    late_changes = [ts for ts in first_seen if ts not in early and len(versions[ts]) > 1]
    if late_changes:
        print(f"WARNING: {len(late_changes)} finished record(s) changed after first sighting: {late_changes}")


if __name__ == "__main__":
    main()
