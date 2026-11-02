# newswitch Architecture & Developer Guide

*How the backend, the arkitekt stack, and the frontend fit together. Written
against `arkitekt` 11.6.1, `arkitekt-runtime` 8.0.1, `arkitekt-spec` 6.3.1 and
`arkitekt-fastapi` 3.0.0, as locked in `backend/uv.lock` (2026-10).
File references are relative to the repo root.*

---

## 1. The big picture

newswitch is a FastAPI app whose entire functional surface is managed by an
**arkitekt agent** embedded in the server. Nothing in the backend defines
REST endpoints for microscope features by hand. Instead, everything is registered
on an app registry, `App("newswitch", app_context=Run)`, which
`create_registry` (`backend/newswitch/microscope/registry.py`) creates fresh for every app.
Nothing reaches an app on import and no run's state is held in a module: modules
declare plain functions and plain `@dataclass` models/states, the part registries of
`newswitch/microscope/apps/` register them by name, and `create_registry` merges the
parts the instrument description calls for (section 2.7):

- **functions** registered with `app.register_action` (in a part registry) become
  remotely callable **actions**,
- **data classes** registered with `app.register_state` become **reactive shared state**
  that is pushed to every browser as JSON-patches,
- **service classes** registered with `app.register_context` (the "managers") are
  **dependency-injected** into those functions by type annotation,
- the frontend **generates typed React hooks** from the backend's schemas
  (a committed export of a complete microscope, `frontend/schemas/`), so UI
  code never hand-writes API calls.

That is how `main_fastapi.py` serves it, the default. newswitch can also be served as a
plain **arkitekt agent** connected to an arkitekt server and shown in Orkestrator
(`main_arkitekt.py`); the microscope's registry is the same, only the
frames and the UI differ (section 6.1).

| Package | What newswitch uses from it |
|---|---|
| `arkitekt` | the `App` facade (the app registry), `Task`, `Service`, `withValidator`, `model_field`, `run` |
| `arkitekt-runtime` | the agent, actors, locks, evented states, the journal |
| `arkitekt-spec` | the declarations (implementations, state/lock schemas, ports) |
| `arkitekt-fastapi` | the served agent: `configure_fastapi`, `/ws`, `/schemas/*`, journal routes, `AsyncAgentTestClient` |

```mermaid
flowchart LR
    subgraph Browser
        UI[React components] --> Hooks[generated hooks<br/>src/apps/default]
        Hooks --> TP[transport layer<br/>src/lib/arkitekt]
    end
    TP -- "REST: /assign /cancel /pause" --> API
    TP <-- "WS /ws: task events,<br/>state patches, locks (journal)" --> API
    TP <-- "WS /stream/frames" --> ENC[FrameBroadcaster]
    subgraph Backend[FastAPI + arkitekt agent]
        API[arkitekt-fastapi routes] --> AG[FastApiAgent]
        AG --> ACT["actors (one per action)"]
        ACT --> MGR["managers (app.register_context):<br/>Values, OpticsManager, DetectorManager, ..."]
        MGR --> ST["states (app.register_state)"]
        ST -- JSON-patch --> AG
        MGR --> DRV["drivers<br/>(newswitch/drivers/base.py)"]
        DRV --> BUS[UC2BusManager]
    end
    BUS --> HW[UC2 hardware<br/>CANopen or serial JSON]
    HW -- telemetry events --> BUS -- dispatch --> ST
    DET[detector loop] --> ENC
```

### 1.1 Values, roles and optics

Everything that can change on a microscope is a **variable** of its description, named by
cube and variable (`stage.z`, `objective.slot`, `laser_488.power`), and it does one of three
things: it moves, it swaps or it tunes. Nothing says what a variable is for. The centre of
the server is what follows from that.

**Values** (`newswitch/services/values.py`) hold what every variable is now, and `Values.set`
is the one way of changing anything. It works out each target (within the variable's range, a
source's power up to its `max_power`, a swap only to a slot it has, or nothing moves), asks the
drivers with `set_together`, grouped by driver type so that what can move together does, and
has each driver report where it got to. Each report is published, and when all are there
`on_change` tells the optics.

A variable reaches the world through a **driver** (`newswitch/drivers/base.py`, a registry with
`register_driver`). `build_drivers` (`newswitch/microscope/parts.py`) picks one per variable: a
detector's own tunes go through its manager (`DetectorTune`), a wired actuator gets the driver its
`driver:` names, and the rest, or all the rest with `simulate: everything`, is simulated. An actuator
a variable names has to be declared in `hardware.actuators`. When a driver fails, `Values.set` raises
and the optics still hear of what did move; nothing retries. `backend/instruments/expected-failures/`
holds descriptions that must be refused, and motors that misbehave, each tested.

A sample always has depth. `Instrument.lit_um` says where the part of it that is seen is: the part
nearest the plane the light makes, a sheet's or the objective's focus. The tracer's defocus comes
from it, so what `Roles` finds follows from what the sample is: in a thin section the stage focuses,
under a sheet in a volume the sheet does. `Simulator._slice` draws the beads in view one by one, each
lit and spread by its own depth, so no volume is stored.

What is published is keyed by cube, then by variable: `MoveState.moves`, `SwapState.swaps`,
`TuneState.tunes`, and `SourceState.sources` by source, so a blok binds
`self.MoveState.moves.stage.z.value`. A change replaces the whole field, and `Values` keeps plain
copies, because arkitekt takes over the class of what is published. `DetectorState.detectors` stays a list, whose
entries do publish.

**Roles** (`newswitch/instrument/roles.py`) say what a variable was found to do. `Roles.found`
nudges every variable from where it starts, for each detector, and traces what changes: what moves
where a detector looks is `sideways`, what changes how sharp its image is and not how large is
`focuses`. Asked for the one that does something (`Roles.one`, `focus`, `x`, `y`), it refuses when
there are none or several, and lists them; a call can name the one it means. Routines reach them
through `newswitch/services/stage.py`: `stage_of(values, detector, focus=None)` is a `Stage`, the
one move per direction a routine drives, and `where(values, detector)` says where a detector looks,
the sum of whatever moves it, which holds however many things do.

**Optics** (`newswitch/services/optics.py`) say what that means. `OpticsManager` compiles the
instrument when it is built, and `refresh` publishes `OpticsState` (`newswitch/states/optics.py`):
a `DetectorOptics` per detector, a `SourceOptics` per source, the `elements` on the way and which
`channels` there are (`newswitch/models/optics.py`). It sets a field only when it changed. A light
path (`LightPath`, `newswitch/models/light_path.py`) is what the description's edges say reaches a
detector. A calibration is looked up by a `LightPathSnapshot.key`, a hash of the detector, its
region and the variables `influences` (`newswitch/instrument/compiler.py`) found to change its
pixels, each to within its step: a calibration holds for as long as those do. Where there is none,
`predicted` says what the optics expect, and `DetectorOptics.calibrated` says which it is.

`build_microscope` wires them together, so a change anywhere ends in `OpticsState`:

```python
calibration.on_change = optics.refresh
if values is not None:
    values.on_change = optics.refresh
if detector is not None:
    detector.on_change = optics.refresh
```

---

## 2. arkitekt concepts, one by one

### 2.1 Agent and actors

arkitekt uses the classic **actor model**. Translated to newswitch:

- The **Agent** (`FastApiAgent`, created by `configure_fastapi` from
  `arkitekt_fastapi` in `backend/main_fastapi.py:create_app`) is the *runtime
  container* for the whole app. It does not do microscope work itself. It owns:
  - `contexts: dict` — the live manager instances (everything
    `app.register_context`), keyed by name (newswitch's own routes do not look
    them up here: they read them off the running agent's contexts, section 6),
  - `states: dict` — the live state instances (everything `app.register_state`),
    each with a revision counter and a serialized ("shrunk") copy,
  - `locks: dict` — named task locks (e.g. `motion`),
  - the **implementation map** — one entry per declared action,
  - the startup/shutdown hooks and background workers,
  - all running **assignments** (tasks) and the actors executing them,
  - the **journal** and a SQLite store (`arkitekt_agent.db`, `db_path` in
    the description's `settings`) that persists it.
- An **actor** is the execution vehicle for one implementation. When a client
  *assigns* a task ("run `move_one` with these args"), the agent routes the
  assignment to the actor for that implementation, which runs the function
  (sync functions in a worker thread via koil, async ones on the loop) and
  reports lifecycle events back (`STARTED`, `PROGRESS`, `YIELD`, `PAUSED`,
  `HELD`, `CANCELLED`, `COMPLETED`, `FAILED`).

In upstream Arkitekt, the agent connects out to an arkitekt server and receives
assignments from there. In newswitch, **arkitekt-fastapi** replaces that
transport: the agent lives inside uvicorn and browsers talk to it directly over
`/ws` + a few REST routes. Same model, no external server. Served by
`main_arkitekt.py` (section 6.1) newswitch does connect out, as a plain
arkitekt agent.

### 2.2 The app context

`App("newswitch", app_context=Run)` declares which class is the
**app context**: `Run` (`backend/newswitch/microscope/run.py`), what one run of newswitch
has: its `Settings`, its instrument, its mikro connection and the one `build_microscope`
they make. `Settings` lives in `backend/newswitch/settings.py` (a pydantic model: the
`settings` section of the instrument's `microscope.yml`).

The object you pass as `app_context=` into `configure_fastapi` travels into
`agent.aprovide(context=...)` and becomes **injectable by type** into hooks and
actions. That's why the startup hooks (`provide_values(run: Run)`, …)
receive it. The served app refuses to start without one: the lifespan calls
`require_app_context` before the agent is entered.

### 2.3 `app.register_startup` — the composition root

```python
# newswitch/microscope/parts.py: data and functions
build_microscope(settings, instrument)     # -> Microscope: a record of every state and manager

# newswitch/microscope/apps/values.py: the variables' own registry
app = App("newswitch", app_context=Run)
app.registry.merge(core.app.registry)

async def provide_values(
    run: Run,
) -> Tuple[Values, MoveState, SwapState, TuneState, SourceState]:
    m = run.microscope                     # one build, on the first hook
    return m.values, m.move_state, m.swap_state, m.tune_state, m.source_state

app.register_startup(provide_values)
```

Startup hooks run **once, when the agent boots** (inside `aprovide`, before
anything is callable). Two pieces of magic, both driven purely by type
annotations:

1. **Parameter inspection**: each parameter is matched by its annotated type
   against (a) the app-context class, (b) already-published state classes,
   (c) already-published context classes. Matching objects are injected.
2. **Return annotation → publication**: the `Tuple[...]` return annotation
   tells the agent what each returned object *is*. Objects whose class/protocol
   is a context go into `agent.contexts`; objects whose class is a state go
   into `agent.states` (serialized, revision 0, immediately subscribable).

So each part is a **registry of its own** (`newswitch/microscope/apps/<part>.py`), and
`create_registry` is the **composition root**: it merges the ones the instrument has. Their startup
hooks (`provide_core`, `provide_values`, `provide_detector`, `provide_uc2`, and `provide_focus` for
the focus group) are plain module-level functions with static return annotations.
Startup hooks get the app context injected (and a service's client, as
`provide_dataset_store(current: Run, client: Mikro)` does; no states or contexts exist yet) and
none sees what another returned, while the parts depend on each other (the simulated
detector reads the values, the optics read the detectors, acquisition and hooks use several
managers, the UC2 drivers and actions share one bus). So all hooks hand out the objects of one
`build_microscope`, made on the first hook and held by the app context, `Run`
(`newswitch/microscope/run.py`). What the instrument lacks is None on the `Microscope` and never
constructed: without a board nothing talks to a bus, without a detector there is no
`DetectorManager`. Everything a hook returns is "published for the rest of the
agent lifecycle" and becomes injectable into every action, background worker and
shutdown hook. If you build a new manager and forget to add it to both the return
*value* and the return *annotation*, injection will fail with
`StateRequirementsNotMet` at call time.

**context dependency** = "give me the live manager instance of this type"
(e.g. `values: Values`). **state dependency** = "give me the live shared
state instance" (e.g. `detector_state: DetectorState`). Contexts are never serialized;
states are.

`app.register_shutdown` hooks run when the agent tears down, after background
workers and running tasks are cancelled: `close_detector` (`newswitch/actions/detector.py`)
ends the live loop and closes the cameras.

### 2.4 `app.register_action` — actions

Any function becomes a remotely callable action:

```python
# newswitch/actions/values.py: a plain function
def move_one(values: Values, task: Task, name: str, to: Optional[float] = None, by: Optional[float] = None) -> None:
    if (to is None) == (by is None):
        raise ValueError(f"Say either where to move {name} or by how much")
    values.set({name: by if to is None else to}, relative=to is None, task=task)

# newswitch/microscope/apps/values.py, merged for every instrument
app.register_action(values.move_one, locks=[locks.MOTION])
```

- Parameters that are contexts/states are injected (invisible to callers);
  everything else becomes the action's *argument schema* (a "port"), which is
  what the frontend codegen turns into a zod schema.
- **Progress and pause**: there is no ambient `progress()`/`pausepoint()`.
  An action takes an injected `task: Task` (from `arkitekt`) and calls
  `task.progress(pct, msg)` and `task.pausepoint()` — that's what powers the
  live progress bar and the pause/step buttons. What reports progress receives
  the task explicitly (`Values.set(targets, relative=False, task=None)`, and on to
  the driver). Tests calling an action directly pass `Task.local()`.
- `locks=[...]` declares the action's locks explicitly, and those are all it holds;
  otherwise they are inferred from the contexts/states it takes (see 2.6 and section 5).
- newswitch declares no `optimistics=[...]`: controls that must answer at once hold
  their own value until the published one arrives (`OptimisticSlider`,
  `frontend/src/components/ui/optimistic_slider.tsx`).
- **Validators** on arguments are blok UtilCalls built with
  `withValidator("len(value) > 0", error_message=...)` (see
  `newswitch/models/acquisition.py`); the frontend
  evaluates them in `frontend/src/lib/arkitekt/calls.ts`.
- An action is a plain function: importing `newswitch/actions/` registers nothing. It becomes an
  action when its part's registry (`newswitch/microscope/apps/<part>.py`) calls
  `app.register_action(fn, ...)`, and reaches an app when `create_registry` merges that part.

### 2.5 `app.register_background` — daemons

`app.register_background` functions are long-running workers started right after
the startup hooks (async ones run on the event loop, sync ones in a dedicated
thread). They use the same injection: `run_uc2_bus(uc2_bus: UC2BusManager)`
gets the live bus. A microscope has three: the detector acquisition loop, the UC2
bus connection pump, and the UC2 event → state dispatcher (`main_arkitekt.py` adds
`publish_camera_streams`).

### 2.6 Registering classes

Models and states are plain `@dataclass`es; registering them does not change the
class, so any number of registries can take the same one.

| Registration | What it does |
|---|---|
| `app.register_context(locks=[...])` | Marks a class (usually a `Protocol`) as an **injectable service** ("manager"). `locks=[...]` are the locks an action taking this context holds, unless it names its own `locks=`. |
| `app.register_state(required_locks=[...])` | Introspects the class into a **state schema** (ports per field) and makes instances *evented*: every `setattr` applies the change under the state's own RLock and publishes a JSON-patch with a new revision to all subscribers. `required_locks` are the locks an action taking this state holds, unless it names its own `locks=`; writes themselves are not checked against locks. |
| `app.register_model` | Marks a dataclass as a **serializable data structure** so it can appear inside action arguments/returns and state fields. Its identifier is `@newswitch/<snake_name>`. Used for value objects (`MoveValue`, `LightPath`, `AcquisitionPlan`, …). No reactivity. Enums travel by member name (`"SEQUENTIAL"`). |
| `@runtime_checkable` | Python stdlib `typing`, not arkitekt — allows `isinstance(obj, SomeProtocol)` structural checks, which the tests use (`isinstance(bus, UC2BusManager)`). |

### 2.7 The app registry and bloks

`app.registry` is the **AppRegistry** of an app — the accumulator for
everything above (implementations, state schemas, locks, bloks, hooks). There
is no global app: `create_registry(instrument, services=())` creates one and merges into it the
part registries of `newswitch/microscope/apps/` the instrument has:

1. `core`, what every microscope has: the models, io, hooks, expanse, calibration, optics,
   metadata, cache, the action `clear_expanse` (`provide_core`);
2. `values`, for any instrument: the states `MoveState`, `SwapState`, `TuneState`, `SourceState`,
   the context `Values` and the verbs `move`, `move_one`, `move_home`, `swap`, `tune`
   (`newswitch/actions/values.py`);
3. `detector`, when it has detectors: `DetectorState`, `DetectorManager`, `AcquisitionManager` and
   `capture_image`, `start_live_view`, `stop_live_view`, `activate_detector`,
   `deactivate_detector`, `set_window` (`newswitch/actions/detector.py`), with the live loop;
4. `uc2`, when the instrument's `hardware` section has a board: `UC2State`, `UC2BusManager`, the
   board's own actions (`newswitch/actions/uc2.py`) and its two background tasks;
5. what needs several things, when all are there: `focus` (something moves + a detector, the state
   `AutofocusState` from `provide_focus`, and `run_autofocus`, `calibrate_light_path`,
   `scan_region`); `acquisition` (something moves + a detector + a source, and `acquire`).

A part merges the parts it names things of, so what reaches an app through two parts counts once.
The part registries hold no per-run state and nothing is declared on them after import.

The detectors send their frames to the context `FrameSink` (a runtime-checkable
protocol, `newswitch.protocols.FrameSink`), and an acquisition stores its datasets in the
context `DatasetStore` (`newswitch/protocols/dataset_store.py`). The core registers both but
provides neither: the entry file provides them, with startup hooks of its own, and passes in the
arkitekt `services` the `App` is created with. The background `run_detector_loop(detector:
DetectorManager, sink: FrameSink)` gets both contexts injected and calls
`detector.acquire_live(sink)`. The registry has no UI and no way to watch the frames
yet: the entry file registers those on the returned app (section 6.1). Without an instrument only the core is merged:
`clear_expanse` is the only action. Every app is run with its own `Run`, which holds its own
microscope, so two apps in one process share nothing:

```python
def create_registry(instrument: Instrument | None, services: Sequence[Service[Any]] = ()) -> App:
    app = App("newswitch", app_context=Run, services=services)
    app.registry.merge(core.app.registry)
    if instrument is None:
        return app

    moves = any(variable.verb == "moves" for variable in instrument.variables.values())
    detectors, sources = instrument.detectors(), instrument.sources()
    app.registry.merge(values.app.registry)
    if detectors:
        app.registry.merge(detector.app.registry)
    if moves and detectors:
        app.registry.merge(focus.app.registry)
    if moves and detectors and sources:
        app.registry.merge(acquisition.app.registry)
    if instrument.hardware.boards:
        app.registry.merge(uc2.app.registry)
    return app

# newswitch/microscope/apps/focus.py: what needs two parts merges them
app = App("newswitch", app_context=Run)
app.registry.merge(values.app.registry).merge(detector.app.registry)
app.register_state(AutofocusState)
app.register_startup(provide_focus)
app.register_action(scan_region, locks=[locks.MOTION])   # run_autofocus, calibrate_light_path

# main_fastapi.py: the transport and the UI, on top
async def provide_frame_broadcaster(run: Run) -> FrameSink:
    return FrameBroadcaster()                # the detectors' sink: the live view's broadcaster

async def provide_no_dataset_store(run: Run) -> DatasetStore:
    return NoDatasetStore()                  # no mikro: an acquisition says so instead of starting

def create_fastapi_registry(instrument: Instrument | None, with_mikro: bool = False) -> App:
    app = create_registry(instrument)
    app.register_startup(provide_frame_broadcaster)
    if with_mikro:
        from newswitch.infra.mikro import app as mikro_app  # needs the extra mikro

        app.registry.merge(mikro_app.app.registry)
    else:
        app.register_startup(provide_no_dataset_store)
    declare_ui(app, instrument)              # the bloks its description holds
    return app
```

The bloks are validated strictly against what was registered: a
blok calling an action this microscope does not have is refused.

You can register **any function** whose non-injected parameters are
serializable types — that's how a new "app" (in the ImSwitch sense) gets its
backend surface. When the server starts, the agent serves a validated, frozen
**snapshot** of the registry.

A blok is different: it ships a **server-defined UI fragment** written in a
JSX-like markup. newswitch's bloks live in the description, as BSX source, written out or named
with `file:`, relative to the description; the views instruments share are in
`backend/instruments/views/`. `declare_ui(app, instrument)` declares its `ui` section, the blok
marked `default` shown first, checked against the catalog the frontend publishes
(`newswitch/infra/ui/newswitch-catalog.json`, written by `cd frontend && yarn catalog:export`, versioned
as `newswitch@<n>` by `NEWSWITCH_CATALOG_VERSION` in `frontend/src/lib/blok/microscope/catalog.tsx`,
which `ui.catalog` names); `declare_agent_ui(app, instrument)` declares its
`agent_ui` section instead (section 6.1). No blok comes from anywhere else. Bloks are served at
`/schemas/bloks` and read by the frontend **at run time** (nothing about the UI is
built into it): it fetches them when it connects, and again on reconnect, and renders
them with its blok renderer (`@arkitektio/bsx`).

A blok's Tailwind classes are compiled **in the browser** (`@arkitektio/bsx/tailwind`, the
Tailwind compiler fed the app's tokens and variants from `frontend/src/theme.css` by
`src/lib/blok/platform.ts`), since
the build never sees them. Bloks
can style by situation with three variants:
- `past:` / `live:` — the app shows the replay timeline, or the live microscope;
- `locked:` — a control (or a microscope panel) whose action a held lock keeps from
  running now, e.g. `<MoveControl className="locked:opacity-60" />` during a move.
  A locked control is marked, not disabled.

Bloks are written in blok
language v2: they bind to states (`{self.MoveState.moves.stage.z.value}`), loop
(`<foreach items={self.DetectorState.detectors} let="camera">`), and invoke actions
(`onClick={self.move_one(name: "stage.z", by: 1.0)}`).
The backend serves their source, and the frontend parses it (`@arkitektio/bsx`). Use them for
small panels that shouldn't require a frontend build.

---

## 3. Boot lifecycle, step by step

What happens when you run `uvicorn main_fastapi:create --factory --port 8069`:

1. **`main_fastapi.create()`** (uvicorn calls the factory, on every reload again):
   `newswitch.settings.load_settings()` reads the `settings` section of the instrument
   `NEWSWITCH_CONFIG` names (unset, or anything but a valid description, is a `SpecError`), and `create_app(settings)` runs. Importing
   modules starts nothing.
2. **`create_app`** builds the FastAPI app, adds auth and CORS middleware, makes the app
   context (`Run.of(config, MikroConnection.from_env())`: the settings, the instrument
   `load_devices(config)` reads, where a mikro is), creates the registry
   (`create_fastapi_registry(run.instrument, with_mikro=run.mikro is not None)`:
   `create_registry(instrument)`, the startup hook `provide_frame_broadcaster` that provides a
   `FrameBroadcaster` as the `FrameSink`, what provides the `DatasetStore`, `declare_ui`), then calls
   **`configure_fastapi(app=fastapi, app_registry=registry.registry, expand_user_from_request=..., app_context=run, db_file=config.db_path)`**
   which:
   - constructs the `FastApiAgent` with the registry + SQLite sink/retriever,
   - mounts the *core* surface immediately: `/ws` (the single multiplexed
     websocket for task events, state patches and lock events) plus
     `/assign`, `/cancel`, `/pause`, `/resume`, `/step`,
   - builds a **lifespan** context manager and installs it via
     **`app.router.lifespan_context = lifespan`**. This is plain FastAPI
     machinery: the lifespan is an async context manager that uvicorn enters
     after binding the port ("startup") and exits on shutdown. arkitekt-fastapi
     *replaces* the app's default lifespan so agent boot/teardown ride on the
     server's own lifecycle.
3. Back in `create_app`, the non-agent routers are mounted: auth and accounts
   (`newswitch/infra/accounts/routes.py`), then the routes of `newswitch/infra/http/`:
   the module-level routers `newswitch.infra.http.liveview.router` at `/stream` (video
   websockets, from the running agent's `FrameBroadcaster`), `newswitch.infra.http.files.router`
   and `newswitch.infra.http.cache.router`.
4. **Server startup → lifespan enters**:
   - the agent swaps its registry for a frozen snapshot and checks the app
     context is there (`require_app_context`),
   - the remaining route groups are mounted (`/tasks`, the journal routes,
     `/states`, `/locks`, per-implementation execution routes, `/assets`, and
     the **schema routes** (the frontend's export, `just export-schemas`, is
     exactly what they serve, taken from a registry snapshot without a server):
     `/schemas/implementations`, `/schemas/states`, `/schemas/locks`,
     `/schemas/bloks`, `/schemas/assets`),
   - OpenAPI is configured, `app.state.agent = agent`,
   - `async with agent:` opens the agent, then **`agent.aprovide(context=run)`**
     is spawned as a task. `aprovide`:
     1. runs every **startup hook** (→ the first `provide_<part>` hook, via `Run.microscope` and `build_microscope`,
        builds the managers and states of everything the instrument has, with what is
        simulated from `settings.simulate`, each variable's driver from the `hardware` section
        and the UC2 transport from the board's `transport`; each hook returns its part's; the
        entry file's `provide_frame_broadcaster` provides the `FrameSink`),
     2. publishes the returned contexts and states,
     3. starts every **background worker** (detector loop, `run_uc2_bus`,
        `run_uc2_event_dispatch`),
     4. begins serving assignments.
5. **Shutdown** reverses it: the provide task is cancelled → background tasks
   cancelled (that's the `CancelledError` path your bus `abackground` must
   re-raise) → running tasks cancelled → **shutdown hooks** run
   (`close_detector`) → agent closes → app exits.

```mermaid
sequenceDiagram
    participant U as uvicorn
    participant F as FastAPI
    participant A as FastApiAgent
    participant S as provide_core / provide_<part> (microscope/apps)
    participant B as app.register_background workers
    U->>F: main_fastapi.create() → create_app(settings) → create_fastapi_registry(instrument)
    F->>A: configure_fastapi (agent + core routes + lifespan)
    U->>F: enter lifespan (server start)
    F->>A: snapshot registry, require app context
    F->>F: mount /tasks /journal /states /locks /schemas
    F->>A: aprovide(context=run)
    A->>S: run startup hooks, one per merged part (inject Run)
    S-->>A: tuples → publish contexts + states
    A->>B: start background workers
    Note over A: ready — /ws accepts clients,<br/>assignments are served
```

---

## 4. Request lifecycle (what a button press does)

1. A component calls a generated hook (`useMoveOne().call({name: "stage.x", to: 100})`).
2. The transport POSTs to **`/assign`** with the implementation name and args;
   the args were validated client-side against the generated zod schema (and
   any `withValidator` calls).
3. The agent records the assignment and hands it to the actor. If another
   running action holds one of the action's **locks**, it waits until that
   lock is released; then the function body runs with its contexts/states and
   `task` injected.
4. Lifecycle events (`STARTED`, `PROGRESS`, …) and `LOCK`/`UNLOCK` frames
   stream to every subscribed client over **`/ws`**; the UI's
   `ProgressDisplay`/lock indicators react. Other clients see the task too
   (`ASSIGN`).
5. Any state mutation inside the call (or from elsewhere, e.g. the UC2
   dispatcher reporting where `stage.x` got to) is JSON-patched over the same socket.
6. Cancel/pause/step buttons hit `/cancel`, `/pause`, `/step`;
   `task.pausepoint()` in the function body is where pauses take effect;
   cancellation raises `CancelledError` inside the body (the UC2 bus turns
   that into a hardware stop command).
7. Every event lands in the **journal**, persisted to SQLite (→ `/replay`).

---

## 5. State, locks and the journal

- A state instance is a normal Python object — **mutating an attribute is
  the entire API** (`detector_state.is_acquiring = True`). The evented subclass publishes
  `{op: replace, path: /is_acquiring, value: true, rev: n}` to the agent, which fans it
  out to `/ws` subscribers; each frontend zustand store applies patches in
  revision order. Thread safety of the write is the state's own RLock. A change inside a
  `dict[str, model]` can be published since `arkitekt-runtime` 8.0.1, but `Values` still
  replaces such a field whole (`self.move_state.moves = _copied(self._moves)`); the entries of
  a list, like `DetectorState.detectors`, are changed in place.
- **Locks are action locks, nothing else.** An action's locks are its
  explicit `locks=` or are inferred from the contexts/states it takes (a
  state's `required_locks`, a context's `locks`). They do two things: an
  action waits until no other running action holds the same lock (real
  mutual exclusion — command exclusivity over a device for a whole
  multi-step operation), and the UI is told (`LOCK`/`UNLOCK`) so it can
  disable conflicting actions. The names are the constants of
  `newswitch/microscope/locks.py`, one per way of changing a microscope (and per
  shared service): `MOTION` (`"motion"`), `SWAP`, `TUNE`, `DETECTOR`, `GALVO`, `IO`,
  `HOOKS` (`"hook_registry"`), `EXPANSE` (`"expanse_state"`), `CACHE`. A move does
  not block changing a laser. The `Values` context and the states of the variables
  carry no lock: `move`, `move_one`, `move_home`, `swap` and `tune` name their verb's,
  `acquire` names `MOTION`, `SWAP` and `TUNE`, and `run_autofocus`,
  `calibrate_light_path` and `scan_region` name `MOTION`. `DetectorState` and the
  `DetectorManager` carry `DETECTOR`, the `AcquisitionManager` carries `EXPANSE` and
  `IO`, and the UC2 actions name theirs explicitly (`stop_stage` and `galvo_stop`
  none, so they work during what they stop).
- **State writes are not checked against locks.** Managers, background loops
  (the UC2 event dispatch) and shutdown hooks write states freely. Writes made
  inside an action through the injected state are attributed to the task
  (the patch carries its `task_id`) and are refused after the task ended;
  writes made by managers or hooks directly carry no task id.
- The **journal** is one ordered record per agent session. Every entry has a
  `pos` (1, 2, 3 … no gaps), a `global_rev`, a `kind`, a `task_id`, …; the
  world at any position is states + tasks + locks. It is served at
  `/journal`, `/journal/{session}`, `/journal/{session}/at/{pos}`,
  `/journal/{session}/at?timestamp=…` and `/tasks/{id}/events`. (arkitekt-fastapi
  also serves `/states/checkout` and `/states/segments`; the frontend does not use them.)

---

## 6. Video streaming (separate from /ws)

Bulk pixels never travel through the state system. The detector background
loop (`run_detector_loop`, `detector.acquire_live(sink)`) pushes frames into the
**`FrameBroadcaster`** (`backend/newswitch/infra/streaming/`; the `FrameSink` `main_fastapi.py` provides),
which keeps the newest frame per detector, by name. Browsers open `WS /stream/frames/{detector}`
(`backend/newswitch/infra/http/liveview.py`, its `router` included by `create_app`;
the first message is the client's auth frame) and get whole frames, one per message: a
header and the detector's own values (`newswitch/infra/streaming/wire.py`), binned to
`max_size` (default 640; 0 sends full size), at most `max_fps` per second (default 30; 0 sends them
all), byte-shuffled and zstd-compressed, which is lossless. The client acknowledges each frame and is sent
the newest one after that, so a slow viewer skips frames and one can join at any time; without
this the server would buffer what a client has not taken yet, without limit. uvicorn runs with
`--ws-per-message-deflate false`: its own compression of every frame takes a core and most
of the frame rate. The frontend shares one socket per detector and size per tab
(`frontend/src/components/liveview/frameStream.ts`).

### 6.1 Two ways to serve

The detectors only know the **`FrameSink`** protocol
(`backend/newswitch/protocols/frame_sink.py`: `start_broadcasting()`,
`broadcast_sync(detector, frame)` from the detector's thread), a context `create_registry`
registers and the entry file provides, like the `DatasetStore` an acquisition stores into. Which
they get, and which UI is declared, is up to the entry file: both start the same way
(`backend/main.py`: settings, then `load_devices(config)`, the instrument the settings point at or
None), call `create_registry(instrument, services=...)`, then
register on the returned app what is particular to them, among it the module-level
startup hooks that provide those (`python main.py fastapi|arkitekt` picks one).

| | `backend/main_fastapi.py` | `backend/main_arkitekt.py` |
|---|---|---|
| Run | `uvicorn main_fastapi:create --factory`, `just dev` | `python main_arkitekt.py`, `just agent` |
| Registry | `create_fastapi_registry(instrument)` → `App` | `create_arkitekt_registry(instrument)` → `App` |
| Sink | `FrameBroadcaster` (`newswitch/infra/streaming/`), provided as the `FrameSink` | `LovekitSink(cameras_of(current.instrument))` (`newswitch/infra/streaming/lovekit.py`), provided as the `FrameSink`; `services=(lovekit_service, mikro_service)` |
| Dataset store | `MikroDatasetStore` when a mikro is configured (`newswitch/infra/mikro/app.py`), else `NoDatasetStore` (`newswitch/infra/mikro/none.py`), which refuses an acquisition | `MikroDatasetStore` (`newswitch/infra/mikro/store.py`) on the client `mikro_service` provides |
| Registers | startup `provide_frame_broadcaster` → `FrameSink`; `provide_no_dataset_store` → `DatasetStore`, or the part `mikro_app` | state `CameraStreams`, startup `provide_lovekit_sink` → `Tuple[FrameSink, CameraStreams]`, startup `provide_dataset_store` → `DatasetStore`, background `publish_camera_streams` (when there are detectors) |
| UI | the description's `ui`, newswitch frontend's catalog (`declare_ui`) | the description's `agent_ui`, the spec's catalogs and Orkestrator's module (`declare_agent_ui`) |
| Frames | `WS /stream/...` (above) | lovekit streams, one per detector |
| Mikro | Configured by hand: `MIKRO_URL`, `MIKRO_DATALAYER_URL`, `MIKRO_TOKEN` (`newswitch/infra/mikro/connection.py`); unset runs without one. Compose has a stack for it: `just mikro`, then `just dev-mikro` | `mikro_service`: the one the arkitekt server provides |
| HTTP routes | auth, accounts, `newswitch/infra/http/`: live view, files, cache | none |

`create_app` includes the module-level routers of `newswitch/infra/http/`:
`liveview.router` at `/stream`, `files.router` (`/files/...`) and `cache.router`
(`/cache/...`). All read what they need off the running agent's contexts
(`running_context(connection, cls)` in `infra/http/__init__.py`, for requests and
websockets): files the `IOManager`, cache the `CacheManager`, the live view the
`FrameBroadcaster` (provided as the `FrameSink`). Before startup the HTTP routes answer
503 and the live-view websocket closes with 1013.

`main_arkitekt.py` runs the registry with `arkitekt.run`, which logs in to the arkitekt
server fakts finds (`--url` / `$FAKTS_URL`); it needs the extra `agent`
(`uv sync --extra agent`), and only it imports lovekit
(`newswitch.infra.streaming` does not import `lovekit.py`).
It runs on any instrument: each detector becomes a lovekit `VideoStream`, keyed by its
cube (stable across restarts) and titled by that too (`cameras_of(instrument)`
→ `list[CameraStream]`). The startup hook `provide_lovekit_sink` provides a
`LovekitSink(cameras_of(current.instrument))` as the `FrameSink`, and a
`CameraStreams`. The `LovekitSink` keeps the newest frame per detector; the background
hook `publish_camera_streams(lovekit, sink: FrameSink, live: CameraStreams)` (a sink
that is not a `LovekitSink` is refused with a `TypeError`) sends what is new, at most `MAX_FPS` (15) per stream,
converting with `to_rgba` off the event loop (~37 ms per 1920×1200 frame). The
declared streams are held in the state `CameraStreams`, which the description's `agent_ui`
bloks show (`<StructureDisplay value={stream} />`). They are checked strictly, offline, against
the spec's catalogs, Orkestrator's module and the registry (`declare_agent_ui`); a description
without the section shows nothing there.
The agent serves no HTTP routes: the files the IO manager writes and the frame
cache are not reachable from Orkestrator, so a frame's cache id or a file handle
points nowhere there (a known gap). So far the agent is tested offline only, with
a fake lovekit client.

---

## 7. Module reference (backend)

| Path | Role |
|---|---|
| `main.py` | **Start here**: the steps both ways of serving share (settings, instrument, registry, serve); `python main.py fastapi\|arkitekt`. |
| `main_fastapi.py` | Served by FastAPI: the startup hooks `provide_frame_broadcaster` (a `FrameBroadcaster` as the `FrameSink`) and `provide_no_dataset_store` (a `NoDatasetStore` as the `DatasetStore`), `create_fastapi_registry(instrument, with_mikro)` → `App` (`create_registry`, those startup hooks, or the part `mikro_app` in place of the second when asked for, `declare_ui`), `create_app` (`configure_fastapi`, auth, accounts, the routers of `newswitch/infra/http/`), the uvicorn factory `create`, `main`. |
| `main_arkitekt.py` | Served as an arkitekt agent: `cameras_of(instrument)`, the startup hooks `provide_lovekit_sink` (a `LovekitSink` as the `FrameSink`, and `CameraStreams`) and `provide_dataset_store` (a `MikroDatasetStore` as the `DatasetStore`), `create_arkitekt_registry(instrument)` → `App` (`create_registry` with `lovekit_service` and `mikro_service`, the state `CameraStreams`, those startup hooks, `publish_camera_streams`, `declare_agent_ui`), `create(current)`, `main` (`arkitekt.run`). |
| `newswitch/tools/` | Tools beside the servers: `check_instrument.py` (prediction, measurement and truth compared). |
| `newswitch/settings.py` | `Settings` (`simulate`, `simulation`, `db_path`, `instrument`, `camera_recording_dir`, `camera_debug_window`, `image_dir`, `cache_dir`), the description's `settings` section, `load_settings` (`NEWSWITCH_CONFIG` names the instrument; unset or invalid, a `SpecError`) and `load_devices(config)` → `Instrument \| None`: the settings and instrument both servers start from. |
| `newswitch/microscope/registry.py` | `create_registry(instrument, services=())`: creates a fresh `App("newswitch", app_context=Run, services=services)` and merges the part registries the instrument has; no UI, no streams (the entry files add those). |
| `newswitch/microscope/apps/` | One registry per part, an `app` each: `models`, `core` (with the contexts `FrameSink` and `DatasetStore`, which the entry file provides), `values`, `detector`, `uc2`, and what needs several: `focus`, `acquisition`. Plain module-level hooks; a part merges the parts it names things of. |
| `newswitch/microscope/run.py` | `Run`, the app context: the settings, the instrument and the mikro of one run, and its one `build_microscope` (`Run.microscope`). |
| `newswitch/microscope/parts.py` | Data and functions: `build_microscope(settings, instrument)` → `Microscope` (a record of every state and manager, what it lacks None), from `build_uc2_bus`, `build_detector_manager`, `build_drivers`. The startup hooks are in `newswitch/microscope/apps/`. |
| `newswitch/microscope/locks.py` | The lock names, one constant per way of changing a microscope (and per shared service): `MOTION`, `SWAP`, `TUNE`, `DETECTOR`, `GALVO`, `IO`, `HOOKS` = `"hook_registry"`, `EXPANSE` = `"expanse_state"`, `CACHE`. |
| `newswitch/infra/http/` | The routes `main_fastapi.py` serves beside the agent (section 6.1), each a module-level `router`: `liveview.py` (`/stream` websockets, from the running `FrameBroadcaster`), `files.py` (`/files/...`, the `IOManager`), `cache.py` (`/cache/...`, the `CacheManager`); `__init__.py`: `running_context(connection, cls)`, the running agent's context for a request or websocket (503 before startup; the live view closes with 1013). |
| `newswitch/actions/` | Plain action, background and shutdown functions, registered by the part registries of `newswitch/microscope/apps/`: `core.py` (`clear_expanse`), `values.py` (`move`, `move_one`, `move_home`, `swap`, `tune`), `detector.py` (`capture_image`, the live view, `activate_detector`, `deactivate_detector`, `set_window`, also `run_detector_loop`, `close_detector`), `space.py` (`move_to`, `set_sample_origin_here`, `register_mount`, `mount_holder`), `uc2.py` (home/stop/LED/galvo/node-scan actions, `run_uc2_bus`, `run_uc2_event_dispatch`). |
| `newswitch/protocols/dataset_store.py`, `newswitch/infra/mikro/store.py`, `newswitch/infra/mikro/none.py` | Where an acquisition goes: `DatasetStore`, provided by the entry file like `FrameSink`. `MikroDatasetStore` writes one `ArrayDataset` of `(t, c, z, y, x)` per position, with its anchors and its place in the stage's space; `NoDatasetStore` refuses, when a server has no mikro. `connection.py` and `app.py` beside them are the mikro of FastAPI mode. |
| `newswitch/routines/` | Multi-step procedures registered as actions: `region_scan.py`, `acquire.py` (an `AcquisitionPlan`, into a `DatasetStore`), `calibration.py`, `autofocus.py`; `common.py` holds what they share (`z_sweep`, `focus_range`, `field_of_view`, `acquire_step`); `affine_matrix.py` (pixel shifts, the pixel→sample scale). The template for porting ImSwitch "apps". |
| `newswitch/protocols/` | The **contracts**: the manager protocols only (`app.register_context`), one module per part or service — `base` (`Manager`, `BackgroundManager`), `detector` (+ `DetectorFrame`, `DetectorSessionInfo`), `uc2` (`UC2BusManager`), `acquisition`, `cache`, `calibration`, `dataset_store`, `expanse`, `io`, `optics`, `metadata`, `hook_manager` (+ `HookContext`, `UnsupportedHook`), `frame_sink` (`FrameSink`: where detectors send frames, provided by the entry file). `Values` is a class, with no protocol. |
| `newswitch/states/` | The states (`app.register_state`): `values.py` (`MoveState`, `SwapState`, `TuneState`, `SourceState`), `detector.py` (`DetectorState`), `optics.py` (`OpticsState`), `uc2.py` (`UC2State`), `io.py` (`IOState`), `hooks.py` (`HookState`), `expanse.py` (`ExpanseState`), `calibration.py` (`CalibrationState`), `autofocus.py` (`AutofocusState`). |
| `newswitch/models/` | The value types (`app.register_model`): `values.py` (`MoveValue`, `SwapValue`, `SwapOption`, `TuneValue`, `LightSource`), `optics.py` (`DetectorOptics`, `SourceOptics`, `OpticalChannel`), `light_path.py` (`LightElement`, `LightEdge`, `LightPath`, `LightPathSnapshot`), `frames.py` (`Frame`, `Image`, `Metadata`), `devices.py` (`Detector`, `DetectorAxis`), `hooks.py`, `calibration.py`, `io.py`, `uc2.py` (typed hardware events), `acquisition.py` (`AcquisitionPlan`, `AcquisitionChannel`, `AcquisitionPosition`, `AcquisitionStack`, `AcquiredDataset`, `ScanOrder`). |
| `newswitch/instrument/` | The description and what follows from it (see "Instruments" below): `spec.py` (`Instrument`, the file validated, pydantic dataclasses all the way down; `load`), `hardware.py` (its `hardware` section), `parts.py` (the `Detector`s from the instrument, `cameras`, `check_wired`), `ui.py` (`BlokEntry`, `UiConfig`: its `ui` and `agent_ui` sections), `errors.py` (`SpecError`), `compiler.py`, `tracing.py`, `predict.py`, `roles.py`, `space.py` (the coordinate graph: systems as nodes, 4x4 maps as edges, a route that may walk one backwards; the sample its hub); the libraries `components/`, `curves/`, `fluorophores/`, `readouts/`, `holders/` (what a sample is mounted on). |
| `newswitch/infra/ui/` | Declaring the description's bloks: the frontend's catalog (`catalog.py`, `newswitch-catalog.json`); `__init__.py`: `declare_ui`, `declare_agent_ui`. |
| `newswitch/drivers/` | What reaches the world: `base.py` (`Driver`, `Simulated`, `SimulatedMove`, `register_driver`, `build_driver`), `simulator.py` (the simulator of an instrument: `Simulator`, `SimulatedMicroscope`), `simulated_detector.py` (`SimulatedDetectorManager`, whose images come from it, keyed by name), `readout.py` (what part of each axis a detector reads, and how: windows and binning, for every manager). |
| `newswitch/drivers/uc2/` | Real hardware: `canopen_bus.py` / `rest_bus.py` / `virtual_bus.py` (transports behind `UC2BusManager`), `event_broker.py` (fan-out), `dispatch.py` (events → states), `actuators.py` (the drivers `uc2.stepper`, `uc2.laser`, `uc2.wheel`, `uc2.turret`) and `uc2_detector.py` (real cameras through uc2_cam_py). |
| `newswitch/services/` | The managers every microscope shares: `values.py` (`Values`), `stage.py` (`Stage`, `stage_of`, `where`), `optics.py` (`OpticsManager`), `acquisition.py`, `cache/`, `calibration.py`, `expanse.py`, `io/`, `metadata.py`, `space.py` (`SpaceManager`: where every pixel, image, well and the stage are on the sample, `move_to`, the mount), `element_facts.py` (what an element is made of, as it should read), `hooks/` (`manager.py`: `PythonHookManager`; `software_autofocus.py`). |
| `newswitch/infra/streaming/` | The `FrameSink`s of the two ways of serving (the protocol, runtime-checkable, is the microscope's: `newswitch/protocols/frame_sink.py`): `FrameBroadcaster` (`frame.py`, the newest frame per detector) and the live view's message format (`wire.py`) for `main_fastapi.py`; `lovekit.py` for `main_arkitekt.py` (`LovekitSink`, `CameraStream`, `CameraStreams`, `publish_camera_streams`, `MAX_FPS`; not imported by the package). |
| `newswitch/infra/` | What serves the microscope, apart from it: it imports the rest of `newswitch`, which never imports it nor the entry files (`tests/test_layering.py`). `accounts/`, `http/`, `streaming/`, `mikro/`, `ui/`, below and above; `export_schemas.py` (`just export-schemas`: `create_fastapi_registry` on `REFERENCE_INSTRUMENT`, its registry snapshot written to `frontend/schemas/`). |
| `newswitch/infra/accounts/` | Users and auth of the FastAPI server: `auth.py` (login, tokens, middleware), `store.py` (the account database), `routes.py` (account management), `cli.py` (account recovery from a shell). (Live view, files and cache are in `newswitch/infra/http/`.) |
| `newswitch/reference/complete-microscope/` | The reference microscope (`microscope.yml`): everything a microscope can have, no views; what the frontend's schemas are exported from. |
| `instruments/` | The microscopes newswitch runs, a folder each, only ever read (see `instruments/README.md`): `fake-microscope/`, the default in the root `.env`; `cam-test/`, one simulated uc2_cam_py camera, with nothing simulated by newswitch; `dual-camera/`, `rgb-camera/`, `point-scanner/`, `light-sheet/`, `flim/`; `views/`, the views they share. |
| `tests/` | pytest; agent-level tests drive the app through `AsyncAgentTestClient` (`arkitekt_fastapi.testing`). |

### The "controller/manager/widget" mapping for ImSwitch veterans

| ImSwitch | newswitch |
|---|---|
| `FooController` + `@APIExport` | `app.register_action` functions (in `actions/` or `routines/`) |
| `FooManager` (device) | a variable and its driver (`drivers/`), through `Values`; else an `app.register_context` Protocol in `protocols/` + implementation in `drivers/` (or `services/`) |
| `CommunicationChannel` signals | `app.register_state` mutations (auto-broadcast) |
| `MasterController` | `build_microscope` (`newswitch/microscope/parts.py`), held by the app context (`Run.microscope`), handed out by the startup hook of each part (`newswitch/microscope/apps/`) |
| React widget + Redux slice + axios file | one component using **generated** hooks |
| setup JSON `availableWidgets` | the `NEWSWITCH_CONFIG` file: what its cubes hold and what can change (`build_microscope` builds, `create_registry` registers), and the views of its `ui` section |

### Instruments: a microscope described by its optical elements

The microscope's only description, read-only, in `backend/instruments/<name>/microscope.yml`
(`newswitch/instrument/spec.py`); its format is in [`backend/instruments/README.md`](../backend/instruments/README.md).
`NEWSWITCH_CONFIG` names it (the file or its folder; the root `.env` and the Dockerfile default it to
`instruments/fake-microscope/microscope.yml`); unset, or anything but a valid description, is a `SpecError`. There is no
other file: its `settings` section says how it runs. newswitch never writes it: what changes while it runs lives in the
arkitekt states, and restarts from each variable's `initial`. It runs in both ways of serving (section 6.1), simulated or
on real hardware.

- `microscope.yml` holds cubes around optical elements, what an actuator does to each (moves, swaps, tunes) and
  how light connects them. A sensor's size is on its axes and nowhere else. Nothing says what impacts what, or what a
  part is for: every variable has a control, and sources and detectors are found from what the cubes hold
  (`Instrument.sources`, `Instrument.detectors`).
- The sample holder is a cube too: its `simulations` name what can be on it, and `settings.simulation` picks one.
  Nothing declares a channel either: `Compiled.channels` reads from the tables which source reaches which detector.
- A cube can name an entry of the components library (`newswitch/instrument/components/`) for its element and its
  hardware signals, and `drives` wires signals together; all of it is validated when the description is parsed. A
  logical detector is a physical detector and what is wired to it: `Instrument.detector_axes` computes what it
  delivers, and an acquisition only loops over the rest, so a detector that steps the stage itself
  takes a stack as one sweep (`DetectorManager.capture_stack`). Point scanners, light sheets and FLIM are built on
  this, in simulation only.
- `newswitch/instrument/compiler.py` works that out when a server starts: it ray traces every combination of swaps
  with optiland, and keeps the result in memory. Nothing is written or cached, so a changed description only takes a
  restart. `tracing.py` is the only module importing optiland. `Roles` and `influences` nudge the variables
  on top of that (section 1.1). `tools/check_instrument.py` is for comparing what the design predicts, what the images
  measure and what was really there.
- The top-level `hardware:` section (`newswitch/instrument/hardware.py`: boards, actuators, cameras) says what the cubes'
  actuator names are wired to, and each actuator states its `driver:`. `settings.simulate`
  (`everything`, `unwired`, `nothing`) says what has no hardware; `check_wired` refuses what cannot be reached. A board
  reaches the hardware over its `transport` (`rest`, `canopen`), and with `simulate: everything` is a `VirtualUC2Bus`.
- `newswitch/instrument/parts.py` gives the `Detector`s the managers take and the cameras to open (`cameras`). The bloks
  are the description's own `ui` and `agent_ui` sections. The detectors are a `UC2DetectorManager` for wired cameras,
  otherwise a `SimulatedDetectorManager`.
- `newswitch/drivers/simulator.py` is the simulator. Only it may read `truth.yml`, the errors the real thing has and
  the description does not know of, which it traces with those applied. Calibration has to
  find them from the images: `uv run python -m newswitch.tools.check_instrument instruments/fake-microscope` compares
  prediction, measurement and truth.

---

## 8. The UC2 hardware layer

`protocols/uc2.py` defines the transport-agnostic **`UC2BusManager`**: stage
verbs in micrometers, laser/LED in raw PWM, galvo in DAC counts, objective
slots, node scan — plus `subscribe()` yielding typed events
(`models/uc2.py`: `PositionUpdate`, `MotionDone`, `HomingChanged`, `EStopChanged`,
`ButtonPressed`, `NodeSeen`, `BusError`).

Three interchangeable implementations (selected in `build_uc2_bus`: the simulator
with `simulate: everything`, else the board's `transport`): **`UC2CanBus`** (CANopen via `uc2canopen.aio`; node map,
µm↔steps scaling, event-driven motion-done from TPDO frames), **`UC2RestBus`**
(serial JSON via `uc2rest.aio`; single ESP32 master, pattern-keyed firmware
events), **`VirtualUC2Bus`** (simulator). Both real buses reconnect with
exponential backoff and surface failures as `BusError` + `UC2State.last_error`.

Two background workers keep it alive: `run_uc2_bus` (owns the connection and
event pump) and `run_uc2_event_dispatch` (consumes `subscribe()` and mirrors
telemetry: a position goes to `Values.reporter` of each `Stepper` on that axis, the rest
to `UC2State`).
The dispatcher writes freely, without a lock and without a task id, so the
reported position streams in while a move holds `motion`. The drivers
(`Stepper`, `Laser`, `Wheel`, `Turret`, `drivers/uc2/actuators.py`) and the board's own
actions (`newswitch/actions/uc2.py`) only ever call bus verbs.

---

## 9. What is the *Expanse*?

The Expanse is newswitch's **sample canvas** — the map of everything imaged of
what is mounted. `ExpanseState` (`states/expanse.py`) holds placed `Image`s and
`Frame`s, each with its pixel→sample affine (`MetadataManager`, from
`SpaceManager.placement`: the pixel scale `calibrate_light_path` measured for the
frame's light path, or else what the optics predict, at where the detector looks,
through the mount). Mounting another holder is a new sample: the expanse is emptied.
`ExpanseManager` adds/clears entries; `AcquisitionManager.acquire`, which `capture_image`
and `scan_region` go through, adds its frames to it. `acquire` does not: a plan's
datasets go to the `DatasetStore`.
The frontend renders it as the three.js scene in `frontend/src/components/stage/`
(planes textured from zarr tiles, camera navigation). `clear_expanse` is the
registered action that empties it. Conceptually it replaces ImSwitch's
StageMap: a persistent, transform-correct mosaic of acquired FOVs.

---

## 10. Frontend in one paragraph

What a backend registers depends on its instrument
(`create_registry`), but the frontend's hooks must cover everything newswitch
can do. So `just export-schemas` (`uv run python -m newswitch.infra.export_schemas`) builds
`create_fastapi_registry` in-process on the reference microscope
`backend/newswitch/reference/complete-microscope/` (`REFERENCE_INSTRUMENT`: everything a
microscope can have, no bloks; it refuses an instrument lacking the states of any part,
`EVERY_PART`), takes a
snapshot of the registry — nothing is started, no app, no startup hooks — and writes
exactly what a FastAPI backend on it serves at `/schemas/implementations|states|locks`
into the committed `frontend/schemas/{implementations,states,locks}.json` — the
mirror of the blok catalog, which the frontend exports for the backend.
`frontend/plugins/generate-app.ts` (a Vite plugin, run on every dev/build)
reads only those files (paths set in `vite.config.ts`; no backend needed, a missing
file fails the build and points at `just export-schemas`) and emits
`src/apps/default/hooks/{actions,states,locks}/*.ts` — zod schemas + typed
hooks (`useMoveOne`, `useMoveState`, …). Bloks are not generated: they are
read at run time (`src/lib/blok/backendUi.tsx`).
The export and the generated files are committed; `just drift-check` (and the
`codegen-drift` CI job) re-exports, rebuilds and fails if `frontend/schemas`,
`frontend/src/apps` diverge from what is committed. The hand-written runtime (`src/lib/arkitekt/`) manages the `/ws` connection, task assignment, patch
application and locks. Its INIT opts into the journal (`journal: true`):
frames then carry `pos` and `journal_session`, and on reconnect the client
sends `resume_after`/`session_id` and receives exactly the frames it missed (a
`resumed` INIT keeps local state; `resync: true` means start over). It also
handles `ASSIGN` (tasks started by other clients), `HELD` (status "held"),
`SESSION_INIT`/`STATE_SNAPSHOT` (state baselines) and accepts
`EFFECT`/`SHELVE`/`UNSHELVE`. The `/replay` page's timeline spans the current
journal session and shows states and locks at the selected time via
`/journal/current/at?timestamp=` (`checkoutAt` in the state context). Bloks
are rendered by the frontend's blok renderer, with the catalog of
`src/lib/blok/microscope/catalog.tsx`. Components (`src/components/microscope/*`) consume only
the generated hooks, and know no part of a microscope: `VariableControl` takes any variable by
name, and `MoveControl`, `SourceControl`, `SwapsControl`, `DetectorControl` and `AcquisitionControl`
show whatever the published states hold. The scene draws a light path from `OpticsState`, along
its edges (`src/components/stage/planes/lightpath/`). If you
add/rename a backend action, state or lock: `just export-schemas`,
`cd frontend && yarn build` (or just `just drift-check`), commit the
regenerated files.

---

## 11. Glossary

| Term | Meaning |
|---|---|
| **App** | An app registry (`arkitekt.App`), created per app by `create_registry`, which merges the part registries into it; its `registry` is what the agent serves. |
| **Agent** | Runtime container managing contexts, states, locks, actors, assignments, the journal. One per app; embedded in FastAPI here. |
| **Actor** | Executor for one registered implementation; handles one assignment at a time, reports lifecycle events. |
| **Assignment / task** | One invocation of an action, with id, args, lifecycle events, journaled history. Injected into the action as `task: Task`. |
| **Implementation** | The registered form of a function: name + argument/return ports + locks + optimistics. |
| **Port** | Typed slot in a schema (an argument, return value, or state field). |
| **Shrinking / expanding** | arkitekt's serialization (Python object → JSON) / deserialization. |
| **Context** | Injectable long-lived service object (`app.register_context`), a.k.a. manager. |
| **State** | Reactive shared data object (`app.register_state`); mutations broadcast as revisioned JSON-patches. |
| **App context** | What one run has (`Run`, declared on `App(..., app_context=...)`: its `Settings`, instrument, mikro, microscope), passed at boot and injectable by type. |
| **Lock** | Named action lock: actions holding the same lock never run at the same time; surfaced to the UI as LOCK/UNLOCK. Does not gate state writes. |
| **Journal** | One ordered record (`pos` 1, 2, 3 …) per agent session; the world at any position is states + tasks + locks. Backs reconnect/resume and `/replay`. |
| **Blok** | Server-defined UI fragment (JSX-like `bsx` markup) rendered by the frontend without a frontend build. |
| **Expanse** | Stage-space canvas of all placed/acquired images (the world map). |
| **Variable** | What can change on a microscope, named by cube (`stage.z`): it moves, swaps or tunes, through a driver, and `Values.set` is the one way of changing it. |
| **Light path** | Every way light can take to a detector, as the description's edges say (`LightPath`); a calibration is keyed by what changes its pixels (`LightPathSnapshot.key`). |
