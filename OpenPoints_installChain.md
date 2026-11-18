# Open points: install chain (Docker image, GitHub Actions, Raspberry Pi)

One entry per open point: number, date logged, short description, detailed description.
Delete an entry once it is done; numbers are not reused. Next free number: **17**.
Entries that need a change in **another repository** say so in their heading
(`[OTHER REPO: <name>]`).

The chain itself: `Dockerfile`, `docker/`, `.github/workflows/build-container.yml`; how to
install it on a Pi: [docs/INSTALL-RPI.md](docs/INSTALL-RPI.md).

---

## 1 · 2026-11-17 · Location and licence of the HikRobot MVS packages

The MVS 5.1.1 packages (`MVS-5.1.1_{aarch64,x86_64}_20261016.deb`, 168 / 182 MB) are read
from `backend/external/` by `docker/install-drivers.sh` (see `backend/external/README.md`).
They are not in git: GitHub rejects files over 100 MB. CI downloads them from a release asset
(default: pre-release `mvs-sdk-5.1.1` of this repository, override with the repository
variable `MVS_SDK_BASE_URL`).

To decide:
- Final location: this repository's releases, `openUC2/ImSwitchDockerInstall` releases (where
  ImSwitch keeps MVS 3.0.1), or a dedicated repository; and whether `backend/external` stays
  the local path.
- Licence: may images that contain the SDK be published (public GHCR package)? The
  uc2_cam_py README says not to publish wheels with the MVS libraries before HikRobot's terms
  are clarified; the same applies to images and to a public release asset. ImSwitch already
  ships MVS 3.0.1 this way. Note: the pre-release `mvs-sdk-5.1.1` and the package
  `ghcr.io/openuc2/newswitch` (tags `pr-11`, `sha-92e9507`) are already public - an anonymous
  pull works (checked 2026-11-18).

## 2 · 2026-11-17 · [OTHER REPO: UC2_cam_py] Make bundling the MVS SDK into the wheel optional

uc2_cam_py always copies the MVS runtime libraries into its wheel (`uc2_cam_py/_mvs/...`,
RPATH `$ORIGIN/_mvs/lib/<arch>`); there is no CMake option to turn that off. In the image the
drivers therefore exist twice: in `/opt/MVS` (HikRobot's installer, 405 MB, `LD_LIBRARY_PATH`)
and in the venv (`_mvs`, 50 MB). Measured on the amd64 image (2026-11-17): at runtime the
extension loads the **venv copy** - the RPATH wins over `LD_LIBRARY_PATH` (`ldd` resolves
`libMvCameraControl.so` to `uc2_cam_py/_mvs/lib/64/`, and uc2_cam_py logs "Using the MVS SDK in
.../_mvs"); `/opt/MVS` is only used for the build. Decision: there must be exactly one final
location of the drivers, `/opt/MVS`.

Needed in UC2_cam_py: an option (e.g. `HIK_BUNDLE_MVS=OFF`) that skips the `_mvs` copy and
lets the extension find the SDK through `MVS_ROOT` / `LD_LIBRARY_PATH` (RUNPATH to
`MVS_ROOT/lib/<arch>`, or none). Then set it in the `Dockerfile` (`CMAKE_ARGS`) and check with
`ldd` that `_hik*.so` resolves `libMvCameraControl.so` from `/opt/MVS`.

## 3 · 2026-11-17 · Install chain without the HikRobot driver

The image always installs MVS and builds uc2_cam_py with `HIK_MVS=ON`; the build fails
without the packages. Not every setup has a HikRobot camera. Options:
- a build argument (e.g. `WITH_HIK=0`) that skips MVS in `install-drivers.sh` and builds with
  `HIK_MVS=OFF` (simulated camera only), published as a separate tag (e.g. `edge-nohik`);
- one image with the driver for everyone (it does no harm without a camera; costs about
  400 MB and needs the licence question of #1 answered);
- leaving out the extra `camera` entirely for setups without any camera.

## 4 · 2026-11-17 · Remove X11 for the camera debug window again

X11 is only in the chain for uc2_cam_py's debug window (`camera_debug_window` in
`backend/base_config.yaml`). Remove later:
- `docker/install-drivers.sh`: `libx11-6 libx11-dev` (block "X11 for the camera debug window");
- `docker/docker-compose.x11.yml`;
- `docker/rpi-host-setup.sh`: `xauth` and the X11Forwarding hint;
- `docs/INSTALL-RPI.md`: section "Camera debug window";
- set `camera_debug_window: false` for the image (without a display it only logs an error).

Related: without a display the MVS library prints `*******XOpenDisplay Fail *******` to stdout
when uc2_cam_py is imported (it ends up in `docker logs`); harmless, but noise.

## 5 · 2026-11-17 · Runtime data is lost when the container is re-created (high priority)

Decision for now: the persistent files stay where they are, relative to the backend folder
(`/opt/newswitch/backend` in the image): `agent_data.db`, `auth.db`, `backend.log`,
`configs/*.persistent.yaml` (+ `.bak`), `data/recordings`. They live in the container's
writable layer: they survive restarts and reboots, but **not** a re-created container, which
every image update does (`docker compose pull && up -d`). The accounts then fall back to
admin/admin. `docs/INSTALL-RPI.md` describes a backup with `docker cp`.

To decide: a host folder for this data (e.g. `/home/pi/NewSwitch`, analogous to ImSwitch's
`/home/pi/ImSwitchConfig` and `/home/pi/Datasets`) mounted as a volume. That needs
configurable paths: `NEWSWITCH_AUTH_DB` exists; `db_path`, `log_file_path`,
`persistent_config_path` and `camera_recording_dir` come only from `base_config.yaml`
(an image-specific base config, or environment overrides). Also a `volume-setup` service as
in ImSwitch (`chown 1000:1000`).

## 6 · 2026-11-17 · Images with a version tag are not built automatically

`build-container.yml` tags `vX.Y.Z` images when a `v*` tag is pushed. semantic-release
(`release.yml`) pushes its tags with `GITHUB_TOKEN`, and events caused by `GITHUB_TOKEN` do not
start other workflows, so no version-tagged image appears. Options: call the build from
`release.yml` (`workflow_call` with the new version), or let semantic-release push with a
GitHub App / PAT token. Besides, the release workflow is red at the moment (backend tests).

## 7 · 2026-11-17 · Keep the pinned base images up to date

The `Dockerfile` and `backend/Dockerfile` pin `ghcr.io/astral-sh/uv:0.12.24-python3.13-trixie-slim`
by digest (reproducible builds). Nothing updates it: add Dependabot (`docker` ecosystem) or
updatecli. `node:22-slim` (frontend stage) is a floating tag; pin it too.

## 8 · 2026-11-17 · Device access of the container: USB cameras, GigE, CAN

`docker/docker-compose.yml` follows ImSwitch's Forklift compose (cgroup rules 188 and 166 for
USB serial, groups tty/dialout/video/plugdev) and adds `a 189:* rwm` for raw USB, which
HikRobot USB3 Vision cameras need. Verified on an amd64 host (2026-11-17, MV-CA023-10UM): the
container finds and opens the camera and grabs frames. On the Pi 5 (arm64, image `pr-11`,
2026-11-18) the container finds the camera too (`list_cameras()`), but no images reach the
frontend (to debug natively first: `.claude/OpenPoints.md` #43). Not covered yet:
- GigE cameras: discovery by broadcast needs `network_mode: host` (or macvlan), plus the
  sysctl settings of `docker/host/80-hikrobot-cameras.conf`;
- CAN over socketcan (`can0` of a CAN HAT lives in the host's network namespace): needs
  `network_mode: host`. CAN over a USB-CAN adapter (serial) already works through the cgroup
  rules.

## 9 · 2026-11-17 · The MVS package's installer does host work inside the image

`dpkg -i` runs HikRobot's postinst (`setup.sh`): besides unpacking to `/opt/MVS` it tries to
install udev rules, load kernel drivers (GigE, PCIe), register services (ScriptServer,
logserver) and copies fonts to `/usr/local/Qt-5.6.3`. In a container this does nothing useful
and leaves residue. The SDK also brings its GUI tools (Qt) in `/opt/MVS/bin`, which newswitch
does not need. Alternative: unpack only `MVS.tar.gz` from the package (what `setup.sh` does
with it) and keep `include/`, `lib/` and `license/`; this saves several hundred MB per image.
Weigh against "the driver is installed by the vendor's installer" (as ImSwitch does).

Measured (amd64 build, 2026-11-17): `dpkg -i` exits 0; the postinst reports the expected
failures (no `/etc/udev/rules.d`, no `/etc/init.d`, no `lsmod`, no desktop). Image size 1.44 GB,
of which `/opt/MVS` is 405 MB (after removing `doc/` and `Samples/`) and the venv 381 MB.

## 10 · 2026-11-17 · Device profile of the lab Pi with the HikRobot camera

The Pi profiles (`backend/configs/machines/openuc2-first-cord-30059*.yaml`) leave the camera
out because the old MVS SDK did not fit uc2_cam_py. With MVS 5.1.1 in the image the camera
can be added (see `backend/configs/camTest_hik_config.yaml` for the camera entries).

## 12 · 2026-11-17 · CI is red independently of the install chain

`ci.yml` and `release.yml` now run Python 3.13 only. `build-container.yml` does not depend on
them and is green (PR #11: amd64 272 s, arm64 189 s). The red `CI` jobs of PR #11 (run
44193921885, 2026-11-17) all have known causes (job logs need a login; the first, third and
fourth were reproduced locally):
- `backend-test (ubuntu)`, `backend-coverage`: pytest - only
  `test_autofocus_sweep_finds_focus_on_virtual_microscope` fails in the CI configuration
  (`.claude/OpenPoints.md` #15); macOS passes.
- `backend-test (windows)`: `uv sync` fails - most likely #17 (uc2-rest README encoding).
- `e2e`: `user-management.spec.ts` expects role text `admin`, the UI shows `Administrator`
  (#19); the other three e2e tests pass.
- `codegen-drift`: the drift check passes; only the post step of `setup-uv` fails (#41).
Also: `actions/checkout@v4`, `setup-uv@v6`, `setup-node@v4` and `upload-artifact@v4` in
`ci.yml` / `release.yml` run on the deprecated Node.js 20 (GitHub warns); bump them.

## 13 · 2026-11-17 · [OTHER REPO: os-rpi] Forklift package for newswitch

openUC2 OS deploys ImSwitch as `deployments/imswitch.pkg`; newswitch has no package yet. Add
`deployments/newswitch.pkg` modelled on it:
- `deployment.compose.yml` with the image pinned by tag and digest
  (`ghcr.io/openuc2/newswitch:sha-...@sha256:...`), the devices and groups of
  `docker/docker-compose.yml`, the data folders of #5 and a `volume-setup` service;
- features: HikRobot cameras (udev, sysctl, usbfs, see #14), `frontend` for the Caddy ingress
  under `/newswitch` (the image already serves the frontend there; the API paths behind the
  prefix still need a decision), firewall;
- `newswitch.deploy.yml` with `disabled: true` at first;
- updatecli for new images.
This replaces `docker/docker-compose.yml` and `docker/rpi-host-setup.sh` on openUC2 OS.

## 14 · 2026-11-17 · [OTHER REPO: os-rpi] Feature hikrobot-cameras on the level of MVS 5.1.1

The feature in `deployments/imswitch.pkg` carries the values of MVS 3.0.1 (its comments cite
`MVS-3.0.1_aarch64_20241128.deb`). MVS 5.1.1 additionally sets `usbfs_memory_mb = 2000`
(`set_usbfs_memory_size.sh`) for USB3 cameras. Update the feature (or a shared camera package
for ImSwitch and newswitch); `docker/host/` holds the values.

## 15 · 2026-11-17 · [OTHER REPO: os-rpi] ImSwitch and newswitch must not run at the same time

Only one application may own the serial controller (and the cameras). On openUC2 OS this is
manual today (`forklift plt disable-depl imswitch`, see `docs/INSTALL-RPI.md`). With a
newswitch package (#13) the two deployments should exclude each other.

## 16 · 2026-11-17 · [OTHER REPO: os-rpi / openUC2 docs] Documentation

- docs.openuc2.com has no installation guide for newswitch (nor a working one for ImSwitch);
  add one based on `docs/INSTALL-RPI.md` once #13 exists.
- `docs/PI-HARDWARE-DEVELOPMENT.md` (this repository) describes the native installation on
  the lab Pi (systemd user services); decide whether it stays as a developer setup or is
  replaced by the container.
