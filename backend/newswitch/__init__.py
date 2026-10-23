"""newswitch: a microscope, described by its device configuration, served through arkitekt.

Start at ``backend/main.py`` (how it is built and served: ``main_fastapi.py``,
``main_arkitekt.py``); then:

- `settings`: what it starts from (base_config.yaml, ``NEWSWITCH_CONFIG``);
- `config_io`: the device configuration (devices, ui, agent_ui);
- `microscope`: the configured parts (`parts`) and the app registry they fill (`registry`);
- `routes`: what ``main_fastapi.py`` serves beside the agent (live view, files, cache);
- `actions`, `routines`: what the app offers, per part;
- `models`, `states`: the values exchanged and the states published;
- `protocols`: what each part (and each service) can do;
- `drivers`: the parts' implementations (UC2 hardware, simulation); `services`: the shared
  managers (acquisition, light path, metadata, calibration, hooks, io, cache, expanse);
- `bloks`, `design`, `optikit`: the UI and building a configuration from a design;
- `broadcasters`: where detectors send frames (websocket live view; `lovekit` for the
  agent); `accounts`: users and auth;
- `tools`: building a configuration from a design, exporting schemas, account recovery;
- `reference`: the complete microscope the frontend's schemas are exported from.
"""
