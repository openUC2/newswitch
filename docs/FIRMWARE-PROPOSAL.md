# Proposal for the UC2 motor firmware: a CANopen contract a host can rely on

*2026-11-24, for the maintainers of [youseetoo/uc2-esp32](https://github.com/youseetoo/uc2-esp32),
from bringing up an openUC2 FRAME with newswitch over CANopen (the Pi's own `can0`, no serial
master in between).*

**Firmware observed:**
- motor satellites (nodes 10–13): `UC2_canopen_slave_motor_release_mot{A,X,Y,Z}`,
  `v2026.0.0-beta.4-9-g3c86acd-t20260930173005-pr133`;
- master: `v2026.0.0-beta.4-13-ge86ebf3`.

**Hosts affected:** newswitch (uc2canopen), and ImSwitch (uc2rest), whose FRAME calibration notes
report the same class of problems.

## 1 · Summary

CANopen is the right transport for the FRAME: standard, binary, robust, with broadcasts, object
access, heartbeats and error messages. The problems are in the **meaning** the motor firmware gives
its objects. The firmware has its own objects (`0x2000…`), and several of them leave a host unable
to tell what state a motor is in:

- a position broadcast that alternates with zeros;
- a "homing done" that belongs to an earlier homing;
- no completion for a move that has nothing to do;
- objects that read 0 when queried.

Each host then builds its own workarounds, differently, and gets them wrong in its own way.

We propose a small, written **contract** for the motor node, modelled on the standard motion profile
**CiA 402** (whose controlword/statusword handshake solves exactly these problems), and a
**conformance test** any firmware build can be checked against.

## 2 · What we observed

All observations are from 2026-11-23 on `can0` at 500 kbit/s, with candump and python-canopen, and
newswitch the only other client.

### 2.1 The position broadcast alternates with zeros

TPDO1 (`0x180 + node`) is int32 position, a status byte (bit 0: running), a homing status byte and
two zero bytes. At rest, node 11 sends two kinds of frame every 0.5 s, alternately, on the same
COB-ID:

```
(…5.122)  18B  [8]  00 00 00 00 00 02 00 00     position 0
(…5.622)  18B  [8]  BC 1A FF FF 02 02 00 00     position -58692
(…6.122)  18B  [8]  00 00 00 00 02 02 00 00     position 0
(…6.622)  18B  [8]  BC 1A FF FF 00 02 00 00     position -58692
```

Two parts of the firmware seem to fill the same PDO, one without a position. A host reads the
axis jumping between its position and 0 twice a second.

**Effects:**
- displayed positions flicker;
- a host that reads "where am I now" at rest gets 0 half the time, and moves relative to that go
  wrong. ImSwitch's notes record the same kind of failure over the serial path: a read of `X = -26`
  instead of `63910` that "drove the stage to the end stop".

The status byte also alternates between `00` and `02` at rest; bit 1 is not documented.

### 2.2 Homing status is not tied to a homing request

`homing_status` (`0x2016`, TPDO1 byte 5) stays at 2 (done) after a homing, until the next homing
starts. A host that starts a homing and then waits for "done" sees the *previous* homing's done at
once, and goes on while the axis is still homing.

**Effect:** a centring move commanded right after "homing done" ran into a homing still in
progress, and the axis ended 1.35 mm from its target.

### 2.3 A move with nothing to do never completes

Completion is visible only as the running bit going from 1 to 0. A move to where the axis already
is, or one shorter than the broadcast period, never sets running. uc2canopen's `move_and_wait`
then waits out its full timeout (120 s) before falling back to polling.

**Effect:** a calibration sets X and Y together, and one of them often does not move. A 30 s
routine took 263 s.

### 2.4 Objects that do not hold their value

SDO reads of `motor_actual_position` (`0x2001:1`) and `homing_status` (`0x2016:1`) return 0. That
is true at rest, after homing, and with the axis known to be at -10,000 steps (as the broadcast
showed at the same time). The documentation says `0x2001` is "updated every cycle". Only the
broadcast carries the state.

### 2.5 Positions that look valid and are not

The step count is saved to NVS on every stop and restored on boot (`FocusMotor.cpp`), and it cannot
be set except by homing (`0x2001` is read-only). Nothing tells a host whether the count still
matches the mechanics. After the stage is moved by hand, steps are lost against a hard stop, or
power fails during a move, the count is silently wrong. We saw a count of 112 mm on an axis with
106 mm of travel.

### 2.6 Defaults that cannot work

On a fresh node, homing speed, direction, timeout, back-off and endstop polarity read 0. A homing
started with those values does nothing useful. It is not refused.

### 2.7 Broadcast rate is fixed

A motor node sends TPDO1 every **10 ms while running** (100/s per axis) and every 500 ms at rest,
whatever the host needs. The rate is not configurable through the communication parameters
(`0x1800`).

### 2.8 On the serial path (uc2rest, through the master)

These are reported in ImSwitch's FRAME calibration notes, not reproduced by us:
- a lost reply reads as all zeros;
- the A axis's position sometimes arrives under X;
- absolute moves below 1 µm are silently skipped;
- the `/home_act` completion frame is not parsed.

The JSON protocol has no request ids, mixes events and replies on one stream, and has no versioned
schema.

## 3 · The proposed contract

The idea is to keep the existing objects for compatibility and add CiA 402's handshake on top. In
CiA 402 terms, per axis:

### 3.1 Controlword (rx) and statusword (tx)

Following CiA 402 (`0x6040` / `0x6041`, or in the `0x20xx` range with the same bits):

| Statusword bit | Meaning | Fixes |
|---|---|---|
| 10 **target reached** | the current setpoint is reached, *including* a setpoint where the axis already is | 2.3 |
| 12 **setpoint acknowledged / homing attained** | toggles (or is set) for *this* request; cleared when a new one is accepted | 2.2, 2.3 |
| 13 **homing error / following error** | the request failed (timeout, no endstop) | 2.2 |
| 15 (manufacturer) **referenced** | the position is referenced to the endstop since boot; cleared on boot and on any detected loss (stall, emergency stop) | 2.5 |
| 3 **fault** | with an EMCY message saying which | — |

The host sets a new target and toggles "new setpoint" in the controlword. The node acknowledges
(bit 12), moves, and sets "target reached" (bit 10). A move with nothing to do acknowledges and
reports "target reached" at once. Homing works the same way: start, then "homing attained" or
"homing error" for **this** start.

### 3.2 One position broadcast, one producer

- TPDO1 carries `position actual` (int32) and the statusword (uint16): one mapping, filled by one
  producer.
- No frame with an unfilled position, ever.

### 3.3 Objects hold their values

`position actual` (`0x6064`, or `0x2001`) and the statusword are readable over SDO at any time, with
the same values the broadcast carries.

### 3.4 Configurable rate

- TPDO1 honours its communication parameters (`0x1800`): **inhibit time** (minimum spacing,
  e.g. 20 ms while running) and **event time** (heartbeat-like resend at rest, e.g. 1 s).
- A change in the statusword is always sent at once, subject only to the inhibit time.

### 3.5 Homing that says how it is set up

- Homing parameters with working defaults: direction toward the configured endstop, a moderate
  speed, a timeout.
- Or a homing refused with an error when they are unset.
- One method that uses the current position as home (CiA 402 method 35), so a host can
  reference an axis without moving it, if it knows where the axis is.

### 3.6 Position persistence that says what it is

If the count is restored from NVS at boot, the node reports it as **not referenced** (bit 15
clear) until it is homed. A host can then show it, and refuse moves that need a reference.

### 3.7 A version for the contract

An object (e.g. `0x2510`) with the contract version this firmware implements. A host checks it at
start and knows which of the above it may rely on.

## 4 · Conformance test

A host-side test any build can be checked against, on a node with a motor and an endstop. newswitch
will carry it as `just uc2 conformance --node <id>`:

| # | Do | Expect |
|---|---|---|
| 1 | listen 5 s at rest | position broadcasts all carry the same position; no frame with position 0 unless at 0 |
| 2 | read `position actual` over SDO | equals the last broadcast |
| 3 | move to the current position | acknowledged and "target reached" within 100 ms |
| 4 | move 10 steps | acknowledged, then "target reached"; position = target |
| 5 | home, wait for attained; home again | the second start clears "attained" before setting it again |
| 6 | home with an unreachable endstop and a 2 s timeout | "homing error" within about 2 s, not "attained" |
| 7 | power-cycle the node | "referenced" clear after boot; set after homing |
| 8 | set TPDO1 inhibit time 50 ms, move | broadcasts at most every 50 ms while running |
| 9 | read the contract version | present, and the claimed items pass |

## 5 · What hosts can then drop

newswitch carries these workarounds today (`newswitch/drivers/uc2/canopen_bus.py`), each to be
removed once the matching test passes:

- **ignoring a 0 position** at rest from an axis known elsewhere (2.1);
- **waiting for "homing" to appear** before waiting for "done" (2.2);
- **ending a move** that never reports running after 0.6 s (2.3);
- **trusting commanded positions** over reported ones during calibration (2.1, 2.4);
- **throttling** a moving axis's broadcasts to 10/s on receipt (2.7);
- **writing** homing polarity and back-off before every homing (2.6).

## 6 · Order of work, as we would suggest it

1. **2.1** (one producer for TPDO1) and **3.3** (readable objects): small, and they remove the most
   confusion.
2. **3.1** statusword handshake (target reached, acknowledged, homing attained / error): removes the
   timing workarounds.
3. **3.6** "referenced" and **3.5** defaults: makes a wrong position visible instead of silent.
4. **3.4** configurable rate and **3.7** contract version.
