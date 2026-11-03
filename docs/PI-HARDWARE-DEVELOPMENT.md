# Microscope Pi development deployment

Host: `pi@192.168.0.46`, checkout: `/home/pi/newswitch`, branch:
`feat/controller-mapping-runtime`. Frontend port 5473, backend port 8069.

Hardware profile: `backend/configs/machines/openuc2-first-cord-30059.yaml`.
Migrated from the selected `/home/pi/ImSwitchConfig/imcontrol_setups/FRAME.json`.
The serial master uses 115200 baud and its stable `/dev/serial/by-id/` path.
Motor IDs are A=0, X=1, Y=2, Z=3. X/Y/A retain 0.396 um/step;
Z retains 0.3125 um/step. A is configured as a linear axis, matching the old file.
One LED uses master channel 1, PWM maximum 1023. No LED matrix is installed.
Endstop polarities and homing directions retain the old values. No startup homing.
Initial movement speeds are reduced to 1000 um/s (X/Y/A), 500 um/s (Z);
jog choices are 1, 10, 100 um. Travel bounds were not present and are not invented.
The HikRobot camera is omitted from this stage/LED test profile: the installed MVS
SDK fails to compile with the pinned uc2_cam_py (MV_E_NORESPONSE missing). No
virtual camera is substituted. Camera integration remains a separate follow-up.

Runtime files and private credentials are in `.runtime/` (excluded locally from Git).
Frontend `.env.local` points to the Pi, not the browser computer's localhost.
The frontend runs Vite in `--mode test` to use committed generated API hooks without
rewriting them; this does not enable virtual hardware. Backend mode is `hardware`.
Node 22 is installed separately inside `.runtime/`; the system Node is unchanged.
The two services are systemd user services, initially started manually, not enabled
at boot. The existing Docker deployment remains available for rollback.

After pushing changes from the Mac, on the Pi:

```sh
cd ~/newswitch
git pull --ff-only
cd backend
~/.local/bin/uv sync --locked --no-dev --extra uc2 --extra camera --python 3.12
cd ../frontend
PATH="$HOME/newswitch/.runtime/node-v22.21.1-linux-arm64/bin:$PATH" yarn install --frozen-lockfile --non-interactive
systemctl --user restart newswitch-backend newswitch-frontend
```

Credentials: `cat ~/newswitch/.runtime/auth.yaml` (keep private).
Logs: `.runtime/backend-service.log`, `.runtime/backend.log`.
Status: `systemctl --user status newswitch-backend newswitch-frontend`.

Rollback, ensuring only one application owns the serial controller:

```sh
systemctl --user stop newswitch-backend newswitch-frontend
docker start imswitch-server-1
```

## Network and validation on 2026-11-03

The Pi firewall permits TCP 5473 and 8069 from 192.168.0.0/24 only, using
runtime rich rules in zone nm-shared. These rules are not permanent and need
reapplying after a firewall reload or reboot. The services are also not enabled
at boot. This is an explicitly started hardware test deployment.

Verified: frontend HTTP 200 from the Mac, backend health, authenticated state
queries, UC2_Feather V2.0 connected over serial, and the complete API/WebSocket
LED-off action (channel 1). No axis movement, homing, or LED-on test was run.
The generated persistent YAML is runtime data and excluded from Git.
