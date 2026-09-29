# STATUS

## config_io replaces newswitch/schemas (2026-09-30), implemented, not committed

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
