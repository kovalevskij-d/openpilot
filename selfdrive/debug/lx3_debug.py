#!/usr/bin/env python3
"""
LX3 Palisade Hybrid 2026 — CAN bus debug monitor.

Run on comma 4 via SSH:
  cd /data/openpilot && python3 selfdrive/debug/lx3_debug.py

Modes:
  --mode signals   : live view of key parsed signals (default)
  --mode can       : raw CAN monitor for LX3-specific addresses
  --mode fingerprint : show fingerprint detection result
  --log FILE       : also write output to a log file
"""

import argparse
import binascii
import time
import json
import sys
from collections import defaultdict
from datetime import datetime

# LX3-specific CAN addresses to monitor
LX3_ADDRS = {
  # Bus 1 (ECAN) - standard CAN-FD signals
  (0x065, 1): "STEERING_ANGLE",
  (0x0A0, 1): "BRAKE_ACCEL",
  (0x0CB, 1): "WHEEL_SPEEDS",
  (0x0EA, 1): "SPEED",
  (0x105, 1): "GEAR",
  (0x110, 0): "LKAS_ALT_steering",
  (0x11A, 1): "GAS_PEDAL",
  (0x125, 1): "SPEED_2",
  (0x12A, 1): "SCC_STATUS",
  (0x130, 1): "GEAR_SELECTOR",
  (0x310, 1): "SCC_CONTROL",
  (0x351, 1): "SCC_DETAIL",
  (0x3A6, 1): "LFAHDA_CLUSTER",

  # LX3 non-standard addresses
  (0x3E2, 1): "DOORS_LX3",
  (0x401, 1): "SEATBELT_LX3",
  (0x35A, 1): "BLINKER_LEFT",
  (0x35B, 1): "BLINKER_RIGHT",
  (0x35C, 1): "BLINKER_STALK",
  (0x2F0, 0): "CRUISE_BUTTONS_ACAN",
  (0x10B, 1): "LKA_BUTTON",

  # Hybrid system
  (0x3E0, 1): "HYBRID_SYS_1",
  (0x3E1, 1): "HYBRID_SYS_2",

  # Standard CAN-FD (should NOT exist on LX3)
  (0x411, 1): "DOORS_SEATBELTS_STD (should be missing)",
  (0x413, 1): "BLINKERS_STD (should be missing)",
}


def mode_signals(args):
  """Live view of parsed openpilot signals via cereal messaging."""
  import cereal.messaging as messaging

  sm = messaging.SubMaster(['carState', 'carParams', 'carControl', 'pandaStates'])
  logfile = open(args.log, 'a') if args.log else None

  if logfile:
    logfile.write(f"\n{'='*60}\nLX3 Signal Log — {datetime.now().isoformat()}\n{'='*60}\n")

  print("Waiting for carState messages...")
  while True:
    sm.update(1000)

    if not sm.updated['carState']:
      continue

    cs = sm['carState']

    lines = [
      chr(27) + "[2J",
      f"LX3 Debug Monitor — {datetime.now().strftime('%H:%M:%S')}",
      f"{'='*55}",
      "",
      f"  Car identified:    {sm['carParams'].carFingerprint if sm.updated.get('carParams') or sm.valid.get('carParams') else 'waiting...'}",
      f"  Safety model:      {sm['carParams'].safetyConfigs[0].safetyModel if sm.valid.get('carParams') and len(sm['carParams'].safetyConfigs) > 0 else 'N/A'}",
      "",
      "--- DRIVING SIGNALS ---",
      f"  Speed (vEgo):      {cs.vEgo * 3.6:6.1f} km/h",
      f"  Steering angle:    {cs.steeringAngleDeg:7.1f} deg",
      f"  Steering torque:   {cs.steeringTorque:7.1f}",
      f"  Steering pressed:  {cs.steeringPressed}",
      f"  Steer fault:       {cs.steerFaultTemporary}",
      "",
      "--- PEDALS / BRAKE ---",
      f"  Gas pressed:       {cs.gasPressed}",
      f"  Brake pressed:     {cs.brakePressed}",
      f"  Standstill:        {cs.standstill}",
      "",
      "--- CRUISE ---",
      f"  Cruise available:  {cs.cruiseState.available}",
      f"  Cruise enabled:    {cs.cruiseState.enabled}",
      f"  Cruise speed:      {cs.cruiseState.speed * 3.6:6.1f} km/h",
      f"  Cruise standstill: {cs.cruiseState.standstill}",
      f"  ACC faulted:       {cs.accFaulted}",
      f"  Block PCM enable:  {cs.blockPcmEnable}",
      "",
      "--- SAFETY ---",
      f"  Door open:         {cs.doorOpen}",
      f"  Seatbelt:          {cs.seatbeltUnlatched}",
      f"  Left blinker:      {cs.leftBlinker}",
      f"  Right blinker:     {cs.rightBlinker}",
      f"  Gear:              {cs.gearShifter}",
      "",
      "--- WHEEL SPEEDS ---",
      f"  FL: {cs.wheelSpeeds.fl * 3.6:6.1f}  FR: {cs.wheelSpeeds.fr * 3.6:6.1f}",
      f"  RL: {cs.wheelSpeeds.rl * 3.6:6.1f}  RR: {cs.wheelSpeeds.rr * 3.6:6.1f}",
    ]

    # Panda state
    if sm.valid.get('pandaStates') and len(sm['pandaStates']) > 0:
      ps = sm['pandaStates'][0]
      lines += [
        "",
        "--- PANDA ---",
        f"  Safety model:      {ps.safetyModel}",
        f"  Ignition line:     {ps.ignitionLine}",
        f"  Ignition CAN:      {ps.ignitionCan}",
        f"  Voltage:           {ps.voltage / 1000:.2f} V",
        f"  Faults:            {ps.faults}",
      ]

    output = "\n".join(lines) + "\n"
    print(output)

    if logfile:
      # Log compact JSON every second
      logfile.write(json.dumps({
        "t": time.time(),
        "speed": round(cs.vEgo * 3.6, 1),
        "steerAngle": round(cs.steeringAngleDeg, 1),
        "steerTorque": round(cs.steeringTorque, 1),
        "gas": cs.gasPressed,
        "brake": cs.brakePressed,
        "cruiseEnabled": cs.cruiseState.enabled,
        "cruiseAvail": cs.cruiseState.available,
        "door": cs.doorOpen,
        "seatbelt": cs.seatbeltUnlatched,
        "blinkerL": cs.leftBlinker,
        "blinkerR": cs.rightBlinker,
        "gear": str(cs.gearShifter),
        "accFault": cs.accFaulted,
        "steerFault": cs.steerFaultTemporary,
      }) + "\n")
      logfile.flush()

    time.sleep(0.5)


def mode_can(args):
  """Raw CAN monitor for LX3-specific addresses."""
  import cereal.messaging as messaging

  logcan = messaging.sub_sock('can')
  logfile = open(args.log, 'a') if args.log else None

  if logfile:
    logfile.write(f"\n{'='*60}\nLX3 CAN Log — {datetime.now().isoformat()}\n{'='*60}\n")

  start = time.monotonic()
  msgs = defaultdict(lambda: {"data": b'', "count": 0, "first": time.monotonic()})

  print("Monitoring LX3-specific CAN addresses...")
  while True:
    can_recv = messaging.drain_sock(logcan, wait_for_one=True)
    for x in can_recv:
      for y in x.can:
        key = (y.address, y.src)
        if key in LX3_ADDRS:
          msgs[key]["data"] = y.dat
          msgs[key]["count"] += 1

    if time.monotonic() - start > 0.2:
      dd = chr(27) + "[2J"
      dd += f"LX3 CAN Monitor — {datetime.now().strftime('%H:%M:%S')}\n"
      dd += f"{'='*75}\n"
      dd += f"{'Addr':>6} {'Bus':>3} {'Hz':>5} {'Count':>7}  {'Data':<48} {'Name'}\n"
      dd += f"{'-'*75}\n"

      for key in sorted(msgs.keys()):
        addr, bus = key
        m = msgs[key]
        elapsed = time.monotonic() - m["first"]
        freq = m["count"] / elapsed if elapsed > 0 else 0
        hex_data = binascii.hexlify(m["data"]).decode('ascii')
        name = LX3_ADDRS.get(key, "?")
        dd += f"0x{addr:03X} {bus:>3} {freq:5.1f} {m['count']:>7}  {hex_data:<48} {name}\n"

        if logfile:
          logfile.write(f"{time.time():.3f} 0x{addr:03X} bus{bus} {hex_data} {name}\n")

      # Show missing expected messages
      missing = set(LX3_ADDRS.keys()) - set(msgs.keys())
      if missing:
        dd += f"\n--- MISSING (not seen yet) ---\n"
        for key in sorted(missing):
          addr, bus = key
          dd += f"0x{addr:03X} bus{bus} — {LX3_ADDRS[key]}\n"

      print(dd)

      if logfile:
        logfile.flush()
      start = time.monotonic()


def mode_fingerprint(args):
  """Show fingerprint detection result."""
  import cereal.messaging as messaging

  sm = messaging.SubMaster(['carParams'])
  logfile = open(args.log, 'a') if args.log else None

  print("Waiting for carParams (fingerprint result)...")
  for _ in range(60):
    sm.update(1000)
    if sm.updated['carParams']:
      cp = sm['carParams']
      lines = [
        f"",
        f"LX3 Fingerprint Result",
        f"{'='*55}",
        f"  Car fingerprint:   {cp.carFingerprint}",
        f"  Car name:          {cp.carName}",
        f"  Brand:             {cp.brand}",
        f"  Safety model:      {cp.safetyConfigs[0].safetyModel if len(cp.safetyConfigs) > 0 else 'N/A'}",
        f"  Safety param:      {cp.safetyConfigs[0].safetyParam if len(cp.safetyConfigs) > 0 else 'N/A'}",
        f"  Flags:             {cp.flags}",
        f"  OP longitudinal:   {cp.openpilotLongitudinalControl}",
        f"  Alpha long avail:  {cp.alphaLongitudinalAvailable}",
        f"  PCM cruise:        {cp.pcmCruise}",
        f"  Radar unavailable: {cp.radarUnavailable}",
        f"  Enable BSM:        {cp.enableBsm}",
        f"  Dashcam only:      {cp.dashcamOnly}",
        f"  Min steer speed:   {cp.minSteerSpeed * 3.6:.1f} km/h",
        f"  Wheelbase:         {cp.wheelbase:.3f} m",
        f"  Steer ratio:       {cp.steerRatio:.1f}",
        f"  Mass:              {cp.mass:.0f} kg",
        f"",
        f"  ECU firmware:",
      ]
      for fw in cp.carFw:
        lines.append(f"    {fw.ecu}: addr=0x{fw.address:X} — {bytes(fw.fwVersion)}")

      output = "\n".join(lines)
      print(output)

      if logfile:
        logfile.write(f"\n{datetime.now().isoformat()}\n{output}\n")
        logfile.flush()
      return

  print("ERROR: carParams not received within 60 seconds. Is openpilot running?")


if __name__ == "__main__":
  parser = argparse.ArgumentParser(description="LX3 Palisade Hybrid 2026 debug monitor",
                                   formatter_class=argparse.ArgumentDefaultsHelpFormatter)
  parser.add_argument("--mode", choices=["signals", "can", "fingerprint"], default="signals",
                      help="signals=parsed state, can=raw CAN, fingerprint=car detection")
  parser.add_argument("--log", type=str, default=None,
                      help="log output to file (e.g. /data/lx3_debug.log)")

  args = parser.parse_args()

  if args.mode == "signals":
    mode_signals(args)
  elif args.mode == "can":
    mode_can(args)
  elif args.mode == "fingerprint":
    mode_fingerprint(args)
