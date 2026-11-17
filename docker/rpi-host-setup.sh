#!/usr/bin/env bash
# One-time host setup of a Raspberry Pi (or another Debian-based Linux host) for the newswitch
# container (docker/docker-compose.yml). Running it again is harmless.
#
#   sudo bash docker/rpi-host-setup.sh [user]       (user: default $SUDO_USER, else pi)
#
# These settings belong to the host kernel and udev, so the container cannot make them
# itself. They mirror the feature "hikrobot-cameras" of openUC2 OS (os-rpi:
# deployments/imswitch.pkg) plus the USB buffer size of HikRobot MVS 5.1.1. Once newswitch has
# its own Forklift package in os-rpi, this script goes away (OpenPoints_installChain.md #13).
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
user="${1:-${SUDO_USER:-pi}}"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this script with sudo: sudo bash $0 [user]" >&2
  exit 1
fi
if ! id "$user" >/dev/null 2>&1; then
  echo "User $user does not exist; pass the login user as the first argument." >&2
  exit 1
fi

# ---------- Docker ----------
if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  echo "Docker with the compose plugin is missing. Install it first, e.g.:" >&2
  echo "  curl -fsSL https://get.docker.com | sudo sh" >&2
  echo "then run this script again." >&2
  exit 1
fi
echo "docker: $(docker --version)"

# ---------- HikRobot cameras: udev, network buffers, USB buffer memory ----------
install -m 0644 "$here/host/65-hikrobot-cameras.rules" /etc/udev/rules.d/65-hikrobot-cameras.rules
install -m 0644 "$here/host/80-hikrobot-cameras.conf" /etc/sysctl.d/80-hikrobot-cameras.conf
install -m 0644 "$here/host/newswitch-usbfs.conf" /etc/tmpfiles.d/newswitch-usbfs.conf
udevadm control --reload-rules
udevadm trigger --action=add --subsystem-match=usb --attr-match=idVendor=2bdf
sysctl --quiet --system
systemd-tmpfiles --create /etc/tmpfiles.d/newswitch-usbfs.conf
echo "usbfs_memory_mb: $(cat /sys/module/usbcore/parameters/usbfs_memory_mb)"

# ---------- Groups of the login user ----------
# docker: run compose without sudo; dialout/plugdev: serial controllers and cameras
for group in docker dialout plugdev; do
  if getent group "$group" >/dev/null; then
    usermod -aG "$group" "$user"
  fi
done
echo "groups of $user: $(id -nG "$user")"

# ---------- X11 forwarding for the camera debug window ----------
# X11 is only needed for the camera debug window; remove it later (OpenPoints_installChain.md #4).
# sshd needs xauth for `ssh -Y`; see docker/docker-compose.x11.yml.
if ! command -v xauth >/dev/null 2>&1; then
  apt-get update
  apt-get install -y --no-install-recommends xauth
fi
if command -v sshd >/dev/null 2>&1 && ! sshd -T 2>/dev/null | grep -qi '^x11forwarding yes'; then
  echo "Note: sshd has X11Forwarding off; set 'X11Forwarding yes' in /etc/ssh/sshd_config" \
    "for the camera debug window over ssh -Y."
fi

echo
echo "Host setup done. Log out and in again so that the new groups of $user apply."
