#!/usr/bin/env bash
# Camera drivers of the newswitch container image (run by ../Dockerfile, stage "drivers").
#
# Modelled on ImSwitch's docker/install-drivers.sh, with two differences:
# - Only the HikRobot driver for now (ImSwitch also installs ToupTek, Daheng, Allied Vision,
#   picamera2 and Tucsen).
# - HikRobot MVS 5.1.1 instead of 3.0.1: uc2_cam_py (extra "camera") needs MVS 5.x.
#
# Inputs, provided by the Dockerfile:
#   TARGETPLATFORM  linux/arm64 or linux/amd64 (set by docker buildx)
#   /mnt/external   backend/external of the build context (bind mount), holding the MVS packages
#
# The SDK ends up where HikRobot's installer puts it, /opt/MVS. The Dockerfile points
# LD_LIBRARY_PATH there, and uc2_cam_py builds against it (MVS_ROOT in backend/pyproject.toml).
set -euxo pipefail

apt-get update

# ---------- HikRobot MVS SDK ----------

case "$TARGETPLATFORM" in
"linux/arm64")
  cpu=aarch64
  sha256=a2c89c84799a551748643c9c49f7574cd92633bec197a4f302043e2f51f27c4d
  ;;
"linux/amd64")
  cpu=x86_64
  sha256=d7b3fed09b9e231873a5beda2694c6f8db6e015beec018cc15108018d33013c7
  ;;
*)
  echo "Unknown target platform $TARGETPLATFORM!" >&2
  exit 1
  ;;
esac

# NOTE: the location backend/external is still to be discussed (OpenPoints_installChain.md #1).
# The packages are not in git (GitHub rejects files over 100 MB): for a local build copy them
# there by hand; in CI, .github/workflows/build-container.yml downloads them there from a
# release asset. See backend/external/README.md.
mvs_deb="/mnt/external/MVS-5.1.1_${cpu}_20261016.deb"
if [ ! -f "$mvs_deb" ]; then
  echo "Missing $mvs_deb (backend/external in the build context), see backend/external/README.md" >&2
  exit 1
fi
echo "$sha256  $mvs_deb" | sha256sum --check --strict -

# HikRobot's postinst (setup.sh) unpacks the SDK into /opt/MVS. Its host steps (udev rules,
# kernel drivers, init.d services) have no effect in a container; the host part is
# docker/rpi-host-setup.sh (OpenPoints_installChain.md #9).
dpkg -i "$mvs_deb"
test -f /opt/MVS/include/MvCameraControl.h

# Same clean-up as ImSwitch, plus the samples
mkdir -p /opt/MVS/bin/fonts
rm -rf /opt/MVS/doc /opt/MVS/Samples

# ---------- X11 for the camera debug window ----------

# X11 is only needed for the camera debug window; remove it later (OpenPoints_installChain.md #4).
# libx11-dev lets uc2_cam_py build its live preview window (HAVE_X11), libx11-6 runs it.
apt-get install -y --no-install-recommends libx11-6 libx11-dev

# ---------- Clean up ----------

rm -rf /var/lib/apt/lists/* /tmp/*
