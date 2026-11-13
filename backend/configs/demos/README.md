# UC2 hardware from controller mappings

These two files are reduced from `../newswitch-config.yaml`. They use Christian's
standalone axes, stage references and controller mappings. The runtime adapter in
`newswitch/managers/uc2/yaml_runtime.py` consumes their addresses and parameters.

| File | Motion | Illumination |
| --- | --- | --- |
| `uc2-serial.yaml` | X/Z through one Serial master | Laser, LED and RGB matrix on the same master |
| `uc2-canopen.yaml` | X/Z on direct CAN, nodes 11/22 | Laser/LED on node 21 and matrix on node 20 |

All addresses/calibration values are illustrative. Replace them for the actual
machine before connecting hardware. Automated tests use fake clients, not motors.

## Start

From `backend`:

```bash
uv run python -m newswitch.config_io configs/demos/uc2-serial.yaml
NEWSWITCH_MODE=hardware NEWSWITCH_CONFIG=configs/demos/uc2-serial.yaml uv run --extra uc2 uvicorn main:app --port 8099
# Or select configs/demos/uc2-canopen.yaml for direct CAN.
```

Alternatively, pass startup options directly (from `backend`):

```bash
uv run --extra uc2 python main.py --config configs/demos/uc2-serial.yaml --mode hardware --port 8099
# The same options work with: uv run --extra uc2 python -m newswitch.app
```

`uv run --extra uc2` automatically prepares the Serial/CAN driver dependencies
before startup; a separate `uv sync --extra uc2` is not required. The YAML selects
the connections to use. From the repository root, `just dev` and `just dev-backend`
also prepare these dependencies automatically.

`--config` and `--mode` override their environment variables; omitted options
continue to use the environment and then the base settings. `--host` and `--port`
override `BACKEND_HOST` and `BACKEND_PORT`. Use `--help` for all options.
These are backend CLI arguments; `uvicorn main:app` continues to use environment
variables because uvicorn handles its own command-line arguments. Device YAML is
validated before HTTP startup; missing, malformed or schema-invalid files abort
startup rather than failing later in a background task. `just dev` performs the
same read-only preflight before launching either service.

`NEWSWITCH_CONFIG` selects a device YAML, not a legacy JSON settings file. Relative
paths resolve against `backend`. The input is never overwritten; positions are
written to a separate `<name>.persistent.yaml` next to it. Base settings still work
without environment overrides; `base_config.yaml` selects the default mode and
device file (currently hardware mode with the simulated-camera profile). A custom
`config_file` passed to ImswitchConfig is honored by startup and shutdown too.

The old `uc2_*` hardware overrides are rejected in real mode if set to nondefault
values. Hardware addresses and mechanics must have one authority: the device YAML.
The old flat JSON files and import-script output are not supported startup files.

## Supported mapping contract

| Connection / mapping type | Address |
| --- | --- |
| `uc2-rest` + `serial-motor` | `id`: master stepper ID 0=A, 1=X, 2=Y, 3=Z; `subid` must be 0 |
| `uc2-rest` + `serial-laser` | `id`: master light/PWM channel 0..3; `subid` must be 0 |
| `uc2-rest` + `serial-led-matrix` | One matrix; required placeholder `id: 0`; `subid: 0` |
| `canopen` + `canopen-motor` | `id`: CAN node 1..127; `subid`: zero-based motor index 0..3 |
| `canopen` + `canopen-laser` | `id`: CAN node 1..127; `subid`: zero-based PWM channel |
| `canopen` + `canopen-led-matrix` | `id`: matrix CAN node; default `subid: 0` is unused |

`serial-motor` explicitly selects the known `/motor_act` master-ID interface. It
is a backend addressing contract, not a claim about wiring behind the master.
The old illustrative `canopen-motor {id: 0, subid: ...}` on a Serial controller is
ambiguous and rejected. We do not guess how to translate it. Explicit SDO routes
through a Serial bridge (`/can_act`) need a confirmed firmware contract first.
The runtime names can be adapted once the team agrees on a different schema/domain
vocabulary; no downstream addresses are inferred from device names.

The logical stage direction does not have to match the master's physical axis:
X may refer to a motor with master ID 2, and feedback is translated back to X.
A logical linear axis can use master ID 0, with linear scaling supplied by its own
AxisConfig. Logical X/Y/Z/A use linear units (um) in this YAML adapter;
angular motion/units on A/rx/ry/rz are not supported yet.

A PWM-driven LED uses the same `serial-laser` / `canopen-laser` API as a laser.
`pwm_max` supplies the raw range for each PWM output; it is not guessed or read
from hardware. Application intensity is 0..100 percent. `channels` on a source
means color/spectral count (1 for a PWM output, 3 for an RGB matrix), not an address.
Matrix fill uses 0..255 per RGB channel, and its illumination slider fills gray.
The current matrix convenience API supports exactly one matrix per microscope.

Motor and laser IDs form separate namespaces on Serial: both can use ID 1 on the
same master. Duplicate outputs across logical controllers sharing a physical link
are rejected. One pooled client owns each used physical connection; controllers
sharing it must agree on protocol and transport settings.

## Motion, connection and startup behavior

- Calibration (`steps_per_um`), inversion, travel limits, velocity and acceleration
  are taken from each axis. Values in compatible units are converted by config_io.
  jerk and axes with no step calibration are rejected by this UC2 runtime.
- Optional `move_timeout_s` (default 120), `homing_speed_steps`,
  `homing_direction` and `homing_timeout_ms` are typed axis fields. Homing speed is
  already in hardware steps/s; ordinary velocity/acceleration are in physical units.
- `homing_required` blocks movement until a successful home. Homing is explicitly
  requested, never automatic. An explicit `homing_order` runs sequentially;
  `null` uses parallel homing as specified by the model.
- Commands on one axis are serialized; axes on different controllers can move
  together. Cancellation/error cancels sibling moves and attempts to stop motors.
  Completion means reported controller completion, not independent encoder proof.
- Outputs are switched off before a connection becomes available and again on
  reconnection. Previous brightness is not automatically restored. Reconnect and
  motion errors invalidate reference status.
- Serial selectors must match exactly one port (explicit ports can reconnect if
  temporarily absent). Unsupported transport/request settings fail explicitly.
  Direct CAN currently supports SocketCAN and Waveshare USB-CAN-A.
- Camera mappings are passed independently to Christian's `build_detector_manager`
  and `UC2DetectorManager` (`uv sync --extra camera` on supported Linux/Python 3.12
  systems). Its warning-and-virtual-fallback behavior when the library is absent is
  retained. With no cameras configured the hardware path exposes no fake camera.
  Actuated wheels and undefined Serial bridge mappings remain unsupported; the
  broad main example still contains these and is not a ready-made startup file.

## Mixed devices and split stages

No third demo is needed: to combine these files, keep one StageConfig and its axis
entries, then place each axis/light mapping in the controller that serves it.
The adapter resolves controller_of(axis_key) independently for every axis. Thus
X can be on Serial while Z and all illumination share CAN. Integration tests cover
this split-stage case, pooling, feedback remapping, failures and startup.

```bash
uv run pytest tests/test_yaml_hardware.py -q
```
