#!/usr/bin/env python3
"""
LX3 Palisade Hybrid 2026 — CAN bus debug monitor.

Run on comma 4 via SSH:
  cd /data/openpilot && python3 selfdrive/debug/lx3_debug.py

Modes:
  --mode signals     : live view of key parsed signals (default)
  --mode can         : raw CAN monitor for LX3-specific addresses
  --mode fingerprint : show fingerprint detection result
  --mode autolog     : background logger — starts on boot, waits for car, logs everything
  --log FILE         : also write output to a log file

Auto-start on boot (add to launch_chffrplus.sh):
  PYTHONPATH=/data/openpilot /usr/local/venv/bin/python /data/openpilot/selfdrive/debug/lx3_debug.py --mode autolog &
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

  # SCC_CONTROL for ACCMode monitoring
  (0x1A0, 1): "SCC_CONTROL",

  # Stock camera LKAS_ALT on bus 2 (for angle comparison)
  (0x110, 2): "LKAS_ALT_stock_cam",

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


def mode_sendcan(args):
  """Live monitor of outgoing CAN messages (sendcan) from openpilot."""
  import cereal.messaging as messaging

  logsendcan = messaging.sub_sock('sendcan')
  logfile = open(args.log, 'a') if args.log else None

  if logfile:
    logfile.write(f"\n{'='*60}\nLX3 SendCAN Log — {datetime.now().isoformat()}\n{'='*60}\n")

  start = time.monotonic()
  msgs = defaultdict(lambda: {"data": b'', "count": 0, "first": time.monotonic(), "last_data": []})

  print("Monitoring sendcan (outgoing CAN messages from openpilot)...")
  print("If passive mode is active, no messages will appear until openpilot engages.\n")

  while True:
    sendcan_recv = messaging.drain_sock(logsendcan, wait_for_one=True)
    for x in sendcan_recv:
      for y in x.sendcan:
        key = (y.address, y.src)
        hex_data = binascii.hexlify(y.dat).decode('ascii')
        msgs[key]["data"] = y.dat
        msgs[key]["count"] += 1
        # Keep last 3 data values to show counter progression
        msgs[key]["last_data"].append(hex_data)
        if len(msgs[key]["last_data"]) > 3:
          msgs[key]["last_data"].pop(0)

        if logfile:
          logfile.write(f"{time.time():.3f},TX,0x{y.address:03X},{y.src},{hex_data}\n")

    if time.monotonic() - start > 0.3:
      dd = chr(27) + "[2J"
      dd += f"LX3 SendCAN Monitor — {datetime.now().strftime('%H:%M:%S')}\n"
      dd += f"{'='*90}\n"

      if not msgs:
        dd += "\nNo sendcan messages yet (passive mode — openpilot not engaged)\n"
      else:
        dd += f"{'Addr':>6} {'Bus':>3} {'Hz':>6} {'Count':>7}  {'Latest Data':<50} {'Counter bytes'}\n"
        dd += f"{'-'*90}\n"

        for key in sorted(msgs.keys()):
          addr, bus = key
          m = msgs[key]
          elapsed = time.monotonic() - m["first"]
          freq = m["count"] / elapsed if elapsed > 0 else 0
          hex_data = binascii.hexlify(m["data"]).decode('ascii')

          # Show counter byte progression (byte 2 = counter for most CAN-FD msgs)
          counter_info = ""
          if len(m["last_data"]) >= 2:
            counters = []
            for d in m["last_data"]:
              if len(d) >= 6:
                counters.append(int(d[4:6], 16))  # byte 2 (counter)
            if counters:
              counter_info = f"cnt: {' -> '.join(str(c) for c in counters)}"

          dd += f"0x{addr:03X} {bus:>3} {freq:6.1f} {m['count']:>7}  {hex_data[:50]:<50} {counter_info}\n"

      print(dd)

      if logfile:
        logfile.flush()
      start = time.monotonic()


def mode_autolog(args):
  """Background auto-logger: waits for car, logs fingerprint + signals + raw CAN continuously."""
  import cereal.messaging as messaging

  LOG_DIR = "/data/lx3_logs"
  os.makedirs(LOG_DIR, exist_ok=True)
  session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
  log_path = os.path.join(LOG_DIR, f"lx3_{session_id}.log")
  can_log_path = os.path.join(LOG_DIR, f"lx3_can_{session_id}.log")

  with open(log_path, 'w') as logfile:
    logfile.write(f"LX3 Auto-Logger started — {datetime.now().isoformat()}\n")
    logfile.write(f"Waiting for openpilot and car...\n\n")
    logfile.flush()

    # Phase 1: wait for carParams (fingerprint)
    sm = messaging.SubMaster(['carParams', 'carState', 'pandaStates', 'selfdriveState', 'controlsState', 'carControl'])
    fingerprinted = False

    while not fingerprinted:
      sm.update(2000)
      if sm.updated['carParams'] and sm['carParams'].carFingerprint:
        cp = sm['carParams']
        logfile.write(f"{'='*60}\n")
        logfile.write(f"CAR IDENTIFIED — {datetime.now().isoformat()}\n")
        logfile.write(f"{'='*60}\n")
        logfile.write(f"  Fingerprint: {cp.carFingerprint}\n")
        logfile.write(f"  Brand: {cp.brand}\n")
        logfile.write(f"  Flags: {cp.flags}\n")
        logfile.write(f"  Safety: {cp.safetyConfigs[0].safetyModel if len(cp.safetyConfigs) > 0 else 'N/A'}\n")
        logfile.write(f"  Safety param: {cp.safetyConfigs[0].safetyParam if len(cp.safetyConfigs) > 0 else 'N/A'}\n")
        logfile.write(f"  OP longitudinal: {cp.openpilotLongitudinalControl}\n")
        logfile.write(f"  PCM cruise: {cp.pcmCruise}\n")
        logfile.write(f"  Radar unavail: {cp.radarUnavailable}\n")
        logfile.write(f"  Enable BSM: {cp.enableBsm}\n")
        logfile.write(f"  Dashcam only: {cp.dashcamOnly}\n")
        logfile.write(f"  Wheelbase: {cp.wheelbase:.3f} m\n")
        logfile.write(f"  Steer ratio: {cp.steerRatio:.1f}\n")
        logfile.write(f"  Mass: {cp.mass:.0f} kg\n")
        logfile.write(f"\n  ECU firmware:\n")
        for fw in cp.carFw:
          logfile.write(f"    {fw.ecu}: addr=0x{fw.address:X} — {bytes(fw.fwVersion)}\n")
        logfile.write(f"\n")
        logfile.flush()
        fingerprinted = True
      else:
        # Log panda state while waiting
        if sm.updated.get('pandaStates') and len(sm['pandaStates']) > 0:
          ps = sm['pandaStates'][0]
          logfile.write(f"[{datetime.now().strftime('%H:%M:%S')}] Waiting... "
                        f"ignition_line={ps.ignitionLine} ignition_can={ps.ignitionCan} "
                        f"voltage={ps.voltage/1000:.2f}V faults={ps.faults}\n")
          logfile.flush()

    # Phase 2: continuous signal + CAN + sendcan logging
    logfile.write(f"\n{'='*60}\nContinuous logging started (recv + sendcan)\n{'='*60}\n\n")
    logfile.flush()

    logcan = messaging.sub_sock('can')
    logsendcan = messaging.sub_sock('sendcan')
    can_log = open(can_log_path, 'w')
    can_log.write(f"# LX3 CAN log — {datetime.now().isoformat()}\n")
    can_log.write(f"# dir,timestamp,addr_hex,bus,data_hex,name\n")

    last_signal_log = 0
    last_state_key = ""
    last_acc_mode = -1
    can_msg_counts = defaultdict(int)
    sendcan_msg_counts = defaultdict(int)

    while True:
      # Log raw CAN for LX3 addresses
      can_recv = messaging.drain_sock(logcan)
      for x in can_recv:
        for y in x.can:
          key = (y.address, y.src)
          if key in LX3_ADDRS:
            can_msg_counts[key] += 1
            hex_data = binascii.hexlify(y.dat).decode('ascii')
            can_log.write(f"RX,{time.time():.3f},0x{y.address:03X},{y.src},{hex_data},{LX3_ADDRS.get(key, '')}\n")

          # Track raw ACCMode changes from SCC_CONTROL
          if y.address == 0x1A0 and y.src == 1 and len(y.dat) > 8:
            acc_mode = (y.dat[8] >> 4) & 0x7
            if acc_mode != last_acc_mode:
              logfile.write(f"# ACCMode: {last_acc_mode} -> {acc_mode} at {datetime.now().strftime('%H:%M:%S.%f')}\n")
              logfile.flush()
              last_acc_mode = acc_mode

      # Log ALL sendcan (outgoing CAN messages from openpilot)
      sendcan_recv = messaging.drain_sock(logsendcan)
      for x in sendcan_recv:
        for y in x.sendcan:
          key = (y.address, y.src)
          sendcan_msg_counts[key] += 1
          hex_data = binascii.hexlify(y.dat).decode('ascii')
          can_log.write(f"TX,{time.time():.3f},0x{y.address:03X},{y.src},{hex_data}\n")

          # Parse and log TX 0x110 angle details (every 50th message to avoid spam)
          if y.address == 0x110 and sendcan_msg_counts[key] % 50 == 1:
            d = y.dat
            tq_gain = d[12] if len(d) > 12 else 0
            logfile.write(f"# TX_0x110: cnt={d[2]} tqGain={tq_gain} raw_9_10_11=0x{d[9]:02x}{d[10]:02x}{d[11]:02x} at {datetime.now().strftime('%H:%M:%S.%f')}\n")
            logfile.flush()

      # Log parsed signals every 1 second (was 2s)
      sm.update(0)
      now = time.time()
      if now - last_signal_log >= 1.0 and sm.valid.get('carState'):
        cs = sm['carState']
        entry = {
          "t": round(now, 3),
          "ts": datetime.now().strftime('%H:%M:%S'),
          "speed_kmh": round(cs.vEgo * 3.6, 1),
          "steerAngle": round(cs.steeringAngleDeg, 1),
          "steerTorque": round(cs.steeringTorque, 1),
          "steerPressed": cs.steeringPressed,
          "steerFault": cs.steerFaultTemporary,
          "gas": cs.gasPressed,
          "brake": cs.brakePressed,
          "standstill": cs.standstill,
          "cruiseAvail": cs.cruiseState.available,
          "cruiseEnabled": cs.cruiseState.enabled,
          "cruiseSpeed": round(cs.cruiseState.speed * 3.6, 1),
          "door": cs.doorOpen,
          "seatbelt": cs.seatbeltUnlatched,
          "blinkerL": cs.leftBlinker,
          "blinkerR": cs.rightBlinker,
          "gear": str(cs.gearShifter),
          "accFault": cs.accFaulted,
          "blockPcm": cs.blockPcmEnable,
          "canValid": cs.canValid,
          "canTimeout": cs.canTimeout,
          "steerFaultPerm": cs.steerFaultPermanent,
          "cruiseStandstill": cs.cruiseState.standstill,
          "steerAngleOffset": round(cs.steeringAngleOffsetDeg, 1) if hasattr(cs, 'steeringAngleOffsetDeg') else 0,
        }
        # Panda state
        if sm.valid.get('pandaStates') and len(sm['pandaStates']) > 0:
          ps = sm['pandaStates'][0]
          entry["controlsAllowed"] = ps.controlsAllowed
          entry["safetyTxBlocked"] = ps.safetyTxBlocked
          entry["safetyRxInvalid"] = ps.safetyRxInvalid
          entry["safetyRxChecksInvalid"] = ps.safetyRxChecksInvalid
        # SelfdriveState
        if sm.valid.get('selfdriveState'):
          sd = sm['selfdriveState']
          entry["sdState"] = str(sd.state)
          entry["sdEnabled"] = sd.enabled
          entry["sdActive"] = sd.active
          entry["alertType"] = sd.alertType
          entry["alertText1"] = sd.alertText1
        # ControlsState
        if sm.valid.get('controlsState'):
          ct = sm['controlsState']
          entry["ctActive"] = ct.active
          entry["ctState"] = str(ct.state)
        # CarControl
        if sm.valid.get('carControl'):
          cc = sm['carControl']
          entry["ccEnabled"] = cc.enabled
          entry["latActive"] = cc.latActive
          entry["steerAngleCmd"] = round(cc.actuators.steeringAngleDeg, 1)
        logfile.write(json.dumps(entry) + "\n")

        # Event-driven: log immediately on state changes (not just every 1s)
        state_key = f"{entry.get('cruiseEnabled')},{entry.get('sdState')},{entry.get('alertType')},{entry.get('controlsAllowed')},{entry.get('latActive')},{entry.get('gear')}"
        if state_key != last_state_key:
          logfile.write(f"# STATE_CHANGE at {entry['ts']}: cruise={entry.get('cruiseEnabled')} sd={entry.get('sdState')} alert={entry.get('alertType')} allowed={entry.get('controlsAllowed')} latActive={entry.get('latActive')} gear={entry.get('gear')} spd={entry.get('speed_kmh')}\n")
          last_state_key = state_key
        logfile.flush()
        can_log.flush()
        last_signal_log = now

        # Every 30 seconds, log CAN + sendcan summary
        if int(now) % 30 == 0:
          logfile.write(f"\n# RX summary at {datetime.now().strftime('%H:%M:%S')}:\n")
          for key in sorted(can_msg_counts.keys()):
            addr, bus = key
            logfile.write(f"#   RX 0x{addr:03X} bus{bus}: {can_msg_counts[key]} msgs — {LX3_ADDRS.get(key, '?')}\n")
          missing = set(LX3_ADDRS.keys()) - set(can_msg_counts.keys())
          if missing:
            logfile.write(f"#   MISSING:\n")
            for key in sorted(missing):
              addr, bus = key
              logfile.write(f"#     0x{addr:03X} bus{bus} — {LX3_ADDRS[key]}\n")

          if sendcan_msg_counts:
            logfile.write(f"# TX summary (sendcan):\n")
            for key in sorted(sendcan_msg_counts.keys()):
              addr, bus = key
              logfile.write(f"#   TX 0x{addr:03X} bus{bus}: {sendcan_msg_counts[key]} msgs\n")
          else:
            logfile.write(f"# TX: no sendcan messages (passive mode)\n")

          logfile.write("\n")
          logfile.flush()

      time.sleep(0.01)


import os


if __name__ == "__main__":
  parser = argparse.ArgumentParser(description="LX3 Palisade Hybrid 2026 debug monitor",
                                   formatter_class=argparse.ArgumentDefaultsHelpFormatter)
  parser.add_argument("--mode", choices=["signals", "can", "sendcan", "fingerprint", "autolog"], default="signals",
                      help="signals=parsed state, can=raw CAN, sendcan=outgoing TX monitor, fingerprint=car detection, autolog=background logger")
  parser.add_argument("--log", type=str, default=None,
                      help="log output to file (e.g. /data/lx3_debug.log)")

  args = parser.parse_args()

  if args.mode == "signals":
    mode_signals(args)
  elif args.mode == "can":
    mode_can(args)
  elif args.mode == "fingerprint":
    mode_fingerprint(args)
  elif args.mode == "sendcan":
    mode_sendcan(args)
  elif args.mode == "autolog":
    mode_autolog(args)
