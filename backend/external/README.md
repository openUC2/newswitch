# backend/external: vendor packages for the container image

The production image (`Dockerfile` in the repository root) installs the camera drivers from
this folder (`docker/install-drivers.sh`). For now that is only the HikRobot MVS SDK:

| File | Platform | SHA-256 |
|---|---|---|
| `MVS-5.1.1_aarch64_20261016.deb` | `linux/arm64` (Raspberry Pi 5) | `a2c89c84799a551748643c9c49f7574cd92633bec197a4f302043e2f51f27c4d` |
| `MVS-5.1.1_x86_64_20261016.deb` | `linux/amd64` | `d7b3fed09b9e231873a5beda2694c6f8db6e015beec018cc15108018d33013c7` |

`install-drivers.sh` verifies these checksums and fails the build if the file for the
target platform is missing.

**The packages are not in git.** Each is larger than 100 MB, the per-file limit of GitHub, so
`*.deb` here is git-ignored. Where they come from:

- **Local build:** copy them here by hand (download from HikRobot:
  <https://www.hikrobotics.com/en/machinevision/service/download/>, "MVS" for Linux).
- **CI:** `.github/workflows/build-container.yml` downloads them here before the build, from
  the release asset of the pre-release `mvs-sdk-5.1.1` of this repository (or from the base
  URL in the repository variable `MVS_SDK_BASE_URL`).

Where these packages should finally live, and whether HikRobot's licence allows publishing
images that contain the SDK, is still open: see `OpenPoints_installChain.md` #1.
