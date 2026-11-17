# Installing newswitch on a Raspberry Pi 5 (container image)

newswitch runs on the Pi as one container: the image `ghcr.io/openuc2/newswitch` holds the
backend, the built frontend and the HikRobot camera driver (MVS 5.1.1). It serves everything
on port **8069**: the user interface under `/newswitch/`, the HTTP API and the websockets.
This follows how ImSwitch is shipped (image built by GitHub Actions, pulled on the Pi).

Status: alpha. Open points of this install chain: [OpenPoints_installChain.md](../OpenPoints_installChain.md).
Read section 8 ("Updating") before the first update: runtime data does not survive it yet.

The commands below run on the Pi, over SSH. `<pi>` is its host name or IP address.

---

## 1. Requirements

- Raspberry Pi 5 (8 GB recommended) with a 64-bit OS based on Debian 13 "trixie":
  **openUC2 OS** (Docker included) or **Raspberry Pi OS Lite 64-bit**.
- Login user `pi` (uid 1000) with sudo rights, reachable over SSH.
- Internet access to `github.com` and `ghcr.io`.
- Free space on the SD card for the image (about 1.5 GB, twice that during an update;
  `docker system df` shows it).

```bash
ssh pi@<pi>          # ssh -Y pi@<pi> if you want the camera debug window (section 9)
```

## 2. Stop ImSwitch (and other newswitch installations)

Only one application may use the serial controller and the cameras.

```bash
# openUC2 OS: switch the ImSwitch deployment off (undo: enable-depl, then apply)
forklift plt disable-depl imswitch && forklift plt apply

# ImSwitch started with plain Docker instead:
docker ps                                    # name of the ImSwitch container
docker stop imswitch-server-1
docker update --restart=no imswitch-server-1 # so that it does not return after a reboot

# The native newswitch development setup (docs/PI-HARDWARE-DEVELOPMENT.md), if present:
systemctl --user stop newswitch-backend newswitch-frontend
```

## 3. Install Docker (Raspberry Pi OS only)

openUC2 OS already has Docker. On plain Raspberry Pi OS:

```bash
curl -fsSL https://get.docker.com | sudo sh
```

## 4. Get the deployment files and set up the host

The repository holds the compose file and the host setup script. Use a folder of its own;
`~/newswitch` may already be the native development checkout.

```bash
git clone --depth 1 --branch main https://github.com/openUC2/newswitch.git ~/newswitch-deploy
cd ~/newswitch-deploy
sudo bash docker/rpi-host-setup.sh
exit                 # log out and in again, so the new groups (docker, dialout, plugdev) apply
```

Until the install chain is merged into `main`, clone the branch that holds it
(`--branch buildChain`).

`docker/rpi-host-setup.sh` makes the settings a container cannot make itself: udev rules for
HikRobot cameras, network buffers for GigE cameras, the USB buffer memory for USB3 cameras
(`usbfs_memory_mb = 2000`), the groups of `pi`, and `xauth` for the debug window. Running it
again is harmless.

## 5. Configure

```bash
cd ~/newswitch-deploy
cp docker/.env.example docker/.env
nano docker/.env
```

- `NEWSWITCH_IMAGE`: which image to run. `ghcr.io/openuc2/newswitch:edge` is the latest
  `main`; `:sha-<commit>` pins one commit; `:pr-<number>` is the build of a pull request.
  Available tags: <https://github.com/openUC2/newswitch/pkgs/container/newswitch>.
- `NEWSWITCH_CONFIG`: the device YAML of this microscope, relative to `backend/` of the
  repository (it is in the image), e.g.
  `configs/machines/openuc2-first-cord-30059-mixed.yaml`, or
  `configs/camTest_hik_config.yaml` for a single HikRobot USB3 camera without a UC2 board.
- `NEWSWITCH_MODE`: `hardware`, or `virtual` for the simulated microscope.

If the package is not public yet, log in to the registry once, with a GitHub token that has
the scope `read:packages`:

```bash
echo <token> | docker login ghcr.io -u <github-user> --password-stdin
```

## 6. Start

```bash
cd ~/newswitch-deploy
docker compose -f docker/docker-compose.yml pull
docker compose -f docker/docker-compose.yml up -d
docker compose -f docker/docker-compose.yml ps     # "healthy" after about 30 s
```

The container starts again by itself after a reboot (`restart: always`).

## 7. Check

```bash
curl -s http://localhost:8069/health

# Camera driver in the image, and the cameras it finds
docker compose -f docker/docker-compose.yml exec server \
  python -c "import uc2_cam_py; print(uc2_cam_py.vendors()); print(uc2_cam_py.list_cameras())"
# expected: ['HikRobot', 'Simulated'], plus one CameraInfo per connected camera

docker compose -f docker/docker-compose.yml logs -f              # terminal output
docker compose -f docker/docker-compose.yml exec server tail -f backend.log   # full log
```

In a browser on another computer: `http://<pi>:8069/` (it forwards to `/newswitch/`). Log in
with **admin / admin** and change the password right away (account menu).

## 8. Updating

> **Runtime data is lost on an update.** Accounts (`auth.db`), the agent history
> (`agent_data.db`), the persistent device configuration (`configs/*.persistent.yaml`),
> recordings (`data/`) and the log live inside the container. An update replaces the
> container, and with it these files; the login falls back to admin/admin.
> (OpenPoints_installChain.md #5.) Back them up first if you need them.

```bash
cd ~/newswitch-deploy
C="docker compose -f docker/docker-compose.yml"

# 1. Back up (container stopped, so the databases are consistent)
$C stop
mkdir -p ~/newswitch-backup
for f in auth.db agent_data.db configs data; do
  $C cp -a server:/opt/newswitch/backend/$f ~/newswitch-backup/ 2>/dev/null || true
done

# 2. Update
git pull --ff-only          # compose file and scripts
$C pull
$C up -d

# 3. Restore what you need (here: the accounts), then restart
$C stop
$C cp -a ~/newswitch-backup/auth.db server:/opt/newswitch/backend/auth.db
$C start

docker image prune -f       # remove the old image
```

`cp -a` keeps the owner (uid 1000, the container user `pi`), so the backend can write the
restored files.

## 9. Camera debug window (optional, X11)

uc2_cam_py can show each camera's newest image in a window of its own
(`camera_debug_window: true` in `backend/base_config.yaml`, the default of the image). The
container needs an X server for that. This is meant for debugging and will be removed later
(OpenPoints_installChain.md #4).

```bash
ssh -Y pi@<pi>                 # X11 forwarding: the window opens on your computer
echo $DISPLAY                  # e.g. localhost:10.0
cd ~/newswitch-deploy
docker compose -f docker/docker-compose.yml -f docker/docker-compose.x11.yml up -d
```

The override uses host networking (the SSH forwarding listens on the Pi's localhost) and
passes your X cookie into the container. The backend then listens on port 8069 of the Pi
directly. Without a display only an error is logged and everything else works. Back to
normal: `docker compose -f docker/docker-compose.yml up -d`.

On a Pi with its own desktop, start the same command from a terminal of the desktop session.

## 10. Building the image on the Pi (optional)

Normally GitHub Actions builds the image. To build a local checkout on the Pi instead (slow:
uc2_cam_py and pystackreg are compiled):

```bash
# The MVS package is not in git; copy it from your computer (backend/external/README.md)
scp MVS-5.1.1_aarch64_20261016.deb pi@<pi>:newswitch-deploy/backend/external/

cd ~/newswitch-deploy
docker buildx build --load -t newswitch:local .
echo "NEWSWITCH_IMAGE=newswitch:local" >> docker/.env
docker compose -f docker/docker-compose.yml up -d
```

## 11. Back to ImSwitch

```bash
cd ~/newswitch-deploy
docker compose -f docker/docker-compose.yml down
forklift plt enable-depl imswitch && forklift plt apply      # openUC2 OS
# or, plain Docker: docker update --restart=always imswitch-server-1 && docker start imswitch-server-1
```

## 12. Troubleshooting

| Symptom | Check |
|---|---|
| Container restarts, `unhealthy` | `docker compose -f docker/docker-compose.yml logs`: an invalid or missing device YAML stops the start with a message. |
| UI not reachable from another computer | `curl http://localhost:8069/health` on the Pi. If that works, the firewall blocks the port (openUC2 OS: firewalld, e.g. `sudo firewall-cmd --zone=nm-shared --add-port=8069/tcp`). |
| Serial controller not found | `ls -l /dev/serial/by-id/` on the Pi; the path must match the device YAML. Is ImSwitch still running (section 2)? |
| `vendors()` lacks `HikRobot` | The image was built without the MVS SDK, which should be impossible (the build checks it): pull again. |
| `list_cameras()` finds no HikRobot camera | `lsusb \| grep 2bdf`; `ls -l /dev/bus/usb/*/*` (the camera's node must be `crw-rw-rw-`, set by the udev rule of section 4); `cat /sys/module/usbcore/parameters/usbfs_memory_mb` must be 2000. |

---

## For maintainers: how images are published

- `.github/workflows/build-container.yml` builds `linux/amd64` (runner `ubuntu-24.04`) and
  `linux/arm64` (native runner `ubuntu-24.04-arm`) and pushes `ghcr.io/openuc2/newswitch`
  with the tags of ImSwitch: `edge` (push to `main`), `sha-<commit>`, `pr-<number>`
  (pull requests from this repository), `beta` / `stable` (branches of these names), and
  `X.Y.Z` (tags `vX.Y.Z`, see OpenPoints_installChain.md #6).
- The MVS packages are downloaded before the build from
  `https://github.com/openUC2/newswitch/releases/download/mvs-sdk-5.1.1/`, or from the base
  URL in the repository variable `MVS_SDK_BASE_URL`. One-time setup: create the pre-release
  `mvs-sdk-5.1.1` and attach both `.deb` files (backend/external/README.md).
- A new package on GHCR is private; an organisation admin can make it public
  (OpenPoints_installChain.md #11).
- To try a change before merging, open a pull request: its image is `:pr-<number>`.
