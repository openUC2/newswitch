# STATUS

## config_io: controller mapping, axes as devices, static/persistent (2026-10-15), implemented, not committed

Plan: `~/.claude/plans/sprightly-imagining-moth.md` (approved). This builds on the two
uncommitted PhysVal entries below.

Model (`config_io/devices.py`):
- The device types are lightsource, detector, controller, stage, axis, objective and filter.
  `revolver`, `device_id`, `ConnectedDevice` and all `*Binding` classes are gone.
- `name` is optional and defaults to the key. Device and mapping entries accept further
  keys, which go into `extras: dict` (not in the schema, not written back). PhysVal,
  Trigger, Firmware, connections and the top level stay strict.
- Only a controller has `connection`. Its `mapping` is device key -> `MappingEntry`
  (`type`, `id`, `subid=0`, `pwm_max`). `pwm_max` is required iff `type` contains
  laser/pwm. `(id, subid)` must be unique per controller (error). `firmware` is optional.
- Stage: `axes: {direction: axis key}`. When `homing_order` is set it must list every
  direction exactly once.
- Axis: `steps_per_um` is required but may be null; `inverted`/`homing_required` default
  to false; `pos`/`vel`/`acc`/`jerk` as before. Lightsource gains `pulse_length(_unit)`;
  `max_intensity` is gone. Filter and lightsource `wavelength` are optional.
- Wheel = a stage with one axis whose `pos.preset_vals` names filters/objectives ("null"
  = empty). The adapters derive the filter/objective selection from `selected_index`
  and write it back there and to `pos.value`.

Connections (`connection.py`): CAN uses `canopen` (no `node_id`; `transport` is
required). `can-bus`, top-level `connections:` and named connections are gone. New:
`protocol: simulated` + `transport: {type: simulated}`, which occupies no resource.

References (`references.py`): `references(key, device)` yields `Reference` records, and a
single loop checks them. A missing or non-axis stage axis is an error; a mapping key
without a lightsource/detector/axis/stage is a `ConfigWarning`; the same target twice in a
group (axis in two stages, device in two mappings) is an error; shared resources are
checked across controllers.

Files: `open_config(static, persistent, from_static=...)` reads static or persistent
(persistent is created from static if missing) and always saves into persistent.
`ConfigFile.save` refuses the static path; the two paths must differ. `app.py` uses
`open_config` at startup/shutdown (2 places); `base_config.yaml` comment updated.

Other:
- jsonschema errors follow pydantic discriminators ("'can-bus' is not a known protocol").
- Fix in `writeback._write_phys`: a new member of a block mapping now goes above the
  blank line between devices (via `set_key`).
- New `Configs/newswitch-config.yaml` from OPT1, corrected: no trailing commas, `canopen`,
  camera `id: 0`, duplicate addresses and mappings resolved, serial hat on
  `/dev/ttyACM*` with an empty mapping, usb3 controller with an empty mapping, wheel stage
  `axes: {rz: my-filter-wheel-axis}`, filters from `archiv/`. OPT1 itself is unchanged and
  does not validate (protocol can-bus, trailing commas, ...).
- Regenerated schema; docs updated: `Configs/README.md`, `docs/connection-reference.md`,
  `docs/DEVELOPER_OVERVIEW.md`.
- Tests: `test_references.py` (replaces `test_light_bindings.py`/`test_axis_bindings.py`),
  `test_chain.py` with `tests/config_io/data/Test-Config-{static,persistent}.yaml` (all
  simulated). The other config_io tests are ported.

Checks: config_io gives 139 passed. `pytest -k "not integration"` gives 209 passed and
the 2 known failures (test_api, test_capture_image_api). `ruff format --check` and
`ruff check` are clean. Pylance shows no errors in the opened config_io files and tests;
pyright CLI is not installed, so `config_file.py`, `connection.py`, `test_chain.py`,
`test_load.py`, `test_writeback.py` and `conftest.py` were not type-checked. The app was
started and stopped twice on temp copies (from_static true, then false): the static file
stays byte-identical and the persistent one gets the runtime values.

Open / known:
- `Configs/sample_connections.yaml` still has `node_id: 5` under canopen (not loaded
  anywhere). `Configs/__note__.md` still says unknown parameters are rejected.
- On shutdown, axes without `pos` get `pos.value` = the stage position (0.0) written, and
  changed fields are written in the field's unit (e.g. mm -> um). This was the behavior before too.
- The simulated protocol is configuration-only; there are no simulated managers yet
  (`use_virtual_microscope` still selects the virtual managers).
- `just drift-check` not run (no registered function signatures changed).

## PhysVal.preset_vals dict: value -> name (2026-10-11), implemented, not committed

Plan: `~/.claude/plans/eager-imagining-wren.md` (approved). This builds on the entry below,
which is not committed either.

- The dict form of `preset_vals` is now `dict[float, str]` (value -> name), e.g.
  `{1: short, 10: long}`. The old name -> value form is rejected.
- `preset_values()` returns the keys; `scaled()` converts the keys. Names, order and
  `selected_index` (the index over the keys) stay.
- Writeback (`writeback._numeric_keys`): numeric keys are compared as numbers, so an
  unchanged `{1: short}` is not rewritten as `1.0: short` when another member changes. A
  regression test covers this and fails without the fix.
- The schema is regenerated (`additionalProperties: string`); `Configs/README.md` is updated.
- Checks: config_io gives 111 passed; `just test-backend` gives 181 passed and the 2 known
  failures. ruff is clean, and pyright reports 0 errors in the changed files.

## PhysVal.preset_vals (list/dict/None) + selected_index (2026-10-11), implemented, not committed

Plan: `~/.claude/plans/eager-imagining-wren.md` (approved).

- `PhysVal.preset_vals` (`config_io/values.py`) is `list[float] | dict[str, float] | None`.
  The default is now `None` (was `[]`).
- New `PhysVal.selected_index: int | None` (0-based, like `selected_channel`). It must be
  smaller than the number of presets and must be `None` when there are none. A violation is
  a validation error, not silently reset.
- `preset_values()` returns the numbers in file order for every form. `scaled()` (unit
  conversion) converts list and dict values and keeps names and `selected_index`.
- Writeback: `selected_index` is in `PHYS_MEMBERS`, and `PHYS_VAL_DEFAULTS` has `None` for
  both. Firmware `"limits"` keeps `value` and `selected_index` (`USER_OWNED_PHYS_MEMBERS`).
  A dict is written as a block mapping.
- Adapter: the detector gets `preset_values()`, so dict names are not passed on;
  `Detector`/frontend are unchanged.
- The schema is regenerated (`Configs/schemas/newswitch-config.schema.yaml`), and
  `Configs/README.md` is updated.
- Tests: new cases in `test_values.py`, `test_adapters.py` and `test_writeback.py`.
  config_io gives 110 passed; `just test-backend` gives 180 passed and the 2 known failures.
  ruff is clean, and pyright reports 0 errors in the changed files.

Open / known:
- `selected_index` is not used by any manager or state yet; the detector does not pick the
  selected preset.
- Pre-existing pyright errors in the new `tests/config_io/test_light_bindings.py` (41) and
  `test_axis_bindings.py` (2) come from the merged CAN-connection work, not from this change.

## base_config.yaml replaces config.py (2026-10-02), implemented, committed

Plan: `~/.claude/plans/eager-imagining-wren.md` (approved).

- New `backend/base_config.yaml` (header: belongs to newswitch, do not delete). It holds
  use_virtual_microscope, db_path, available_cubes, config_dir, schema_dir,
  static_config_path, persistent_config_path and load_from_static_config_path.
  server/port are not in it: host and port come from BACKEND_HOST/BACKEND_PORT in the root
  `.env`, and the docker deployment is still open.
- `ImswitchConfig` (`newswitch/app.py`) is now a pydantic-settings `BaseSettings`. It reads
  `BASE_CONFIG_FILE` only (no env), with `extra="forbid"` and no hard-coded defaults.
  - Relative dirs are taken relative to `backend/`; bare file names resolve against `config_dir`.
  - `config_file` = static or persistent path; `ImswitchConfig(config_file=None)` gives virtual
    devices (tests).
  - It has an explicit `__init__(**values)` so pyright does not demand every field.
- With `load_from_static_config_path: false`, startup copies static → persistent once
  (`config_io.ensure_persistent_copy`) and writes back into the persistent file. Its
  `*.persistent.yaml` is git-ignored. Checked by starting the app in a temp folder; the
  static file stayed byte-identical.
- `config_io` now works with explicit paths only: `load_config(path)` and
  `export_schema(path)` have no defaults, and `DEFAULT_CONFIG_NAME` is gone. The CLI
  (`python -m newswitch.config_io`) takes its defaults from `ImswitchConfig`.
- Deleted: `newswitch/config.py` (Paths/get_paths, NEWSWITCH_*_DIR env vars, data/log dir,
  suffix guessing, systemd note) and `tests/test_config_paths.py`. The `platformdirs`
  dependency is dropped; with the newer uv, `uv lock` also normalized a few numpy markers.
- Tests: new `tests/test_app_config.py` and persistent-copy tests in `tests/config_io/test_load.py`.
  `config_io` tests now pass paths (fixture `config_path`).
- Checks: ruff format and lint are clean (the old F401 are gone). pyright reports 0 errors in
  the changed files and 29 in the whole backend, as before. `just test-backend` gives 154
  passed and the 2 pre-existing failures.

Open / known:
- The config_io CLI now imports `newswitch.app`, so it prints a StarletteDeprecationWarning.
- `server`/`port` were removed from `ImswitchConfig` (they were never read).

## VS Code settings + config_io test typing (2026-10-01), implemented, committed

Plan: `~/.claude/plans/eager-imagining-wren.md` (approved).

Cause of the VS Code errors: the Python Environments extension had selected the global Pixi
interpreter (`~/pixiProject/.pixi/envs/default/bin/python3.14`), which lacks ruamel.yaml,
pydantic_settings, fastapi, rekuest_next, ... The project venv is `backend/.venv` (3.12).

- New root `.vscode/settings.json`: interpreter `backend/.venv`, typeCheckingMode `standard`,
  pytest with cwd `backend` (test explorer works when the repo root is opened).
- `backend/.vscode/settings.json`: `strict` → `standard` (strict gave ~420 `reportUnknown*`
  errors from untyped ruamel.yaml), interpreter `.venv`.
- `tests/config_io`: 77 pyright errors fixed, test code only. `DocWriter` is now a `Protocol`,
  the new helper `get_device(config, id, cls)` in `conftest.py` gives typed device access, and
  optional values are narrowed with asserts.
- Checked: pyright (standard, venv) reports 0 errors for config_io, config, app and auth;
  ruff format is clean; config_io tests 82/82 pass.

Manual step (once per machine): an explicit interpreter selection overrides
`defaultInterpreterPath`, so run "Python: Select Interpreter" → `backend/.venv/bin/python`.

Open / known:
- 29 pre-existing pyright errors outside the scope: `managers/helpers/psf.py` (`nipy`) and
  `helpers/frame.py` (`skimage`) import packages that are not in pyproject; there are also
  type issues in `virtual_stage`, `serial_manager`, `broadcasters/*`, `local_cache`,
  `region_scan`, `test_virtual_stage`, `test_affine_matrix`.
- The untracked root `.vscode/launch.json` still points at the removed `example_schemas.py`.

## config_io replaces newswitch/schemas (2026-09-30), implemented, committed

Plan: `~/.claude/plans/elegant-watching-bumblebee.md` (approved). All four phases are done.

- New package `backend/newswitch/config_io/` reads the single file
  `backend/Configs/newswitch-config.yaml` (key = device_id, snake_case keys, types:
  lightsource/detector/controller/stage(+axes)/objective/revolver/filter).
  Validation: jsonschema per type → pydantic dataclasses → cross-device references.
  Write-back via ruamel.yaml keeps comments; `.bak` files are git-ignored.
- Schema (generated): `Configs/schemas/newswitch-config.schema.yaml`,
  `uv run python -m newswitch.config_io --export-schema`.
- App: `ImswitchConfig.config_file` (None = built-in virtual devices, used by the tests;
  `main.py` sets `newswitch-config.yaml`). `@shutdown save_device_config` writes back
  exposure/gain/revolver positions/stage position (re-reads the file first).
- Manager changes: `VirtualDetectorManager(detectors=...)`, and `VirtualObjectiveManager` now
  applies `default_slot`.
- Removed: `newswitch/schemas/`, `example_schemas.py`, 5 old test files, the old
  Configs (Devices*.yml, hik_*, data/*, devices.schema.json, _newswitch-config.yaml); JSON is
  no longer in `CONFIG_SUFFIXES`.
- Tests: `backend/tests/config_io/` (82 tests, green).

Open / known:
- Pre-existing, unrelated: `tests/test_api.py` + `tests/test_capture_image_api.py` fail
  (last event is UNLOCK instead of COMPLETED; they also fail on the original code).
  `config.py` has 3 F401 (platformdirs, for the deployment TODO).
- `just drift-check` not run: frontend deps are not installed (`vite` missing). No registered
  function/state/lock signatures were changed.
- Every dev run writes the example config on shutdown (e.g. `pos.value`).
- Decisions taken without asking (plan section 5): connection XOR controller for all connected
  devices; unconvertible unit → warning + value dropped; axis units um, um/s, um/s**2, um/s**3;
  Illumination.kind from coherence; version check warns on a major/minor mismatch.
- Next plans: rename FilterBank → Revolver (incl. frontend), StageManager with list[axis] +
  AxisManager, controller manager, real firmware reading (`ConfigFile.apply_firmware` is ready).
- Note: the root `.env` has BACKEND_PORT=8069 / FRONTEND_PORT=5473 (CLAUDE.md says 8099/5173).
