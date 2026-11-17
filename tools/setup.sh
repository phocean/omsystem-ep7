#!/usr/bin/env bash
# One-time setup of everything `make firmware` needs, inside this checkout (and the toolchain prefix). Safe to run again:
# each step is skipped when it is already done. Needs network (pip, GNU binutils, the pinned GNU simulator sources, OM's firmware).
#   .venv                 Python 3.12+ environment (EP7_PYTHON=/path/to/python to choose the interpreter) with numpy (requirements.txt)
#   external/oly_fw_analysis   git submodule (emulator harness)
#   $EP7_TOOLCHAIN        mn10300-elf binutils (default ~/ep7fw-toolchains), built from GNU's signed source
#   emulator              pinned GNU MN103 simulator, built under external/oly_fw_analysis/toolchains/
#   stock_firmware/       OM's official E-P7 1.1 file (SHA-256 checked) and its decoded components in analysis/
set -euo pipefail
cd "$(dirname "$0")/.."
. tools/common.sh
export EP7_TOOLCHAIN=${EP7_TOOLCHAIN:-$HOME/ep7fw-toolchains}
OS=$(uname -s)
step() { printf '\n==> %s\n' "$*"; }

# ---- 1. prerequisites -------------------------------------------------------------------------------------------------
step "Checking prerequisites"
missing=()
for c in curl tar make git sed gpgv; do command -v "$c" >/dev/null 2>&1 || missing+=("$c"); done
[ "$OS" = Darwin ] || command -v xz >/dev/null 2>&1 || missing+=("xz")
command -v cc >/dev/null 2>&1 || command -v gcc >/dev/null 2>&1 || missing+=("a C compiler (cc or gcc)")
command -v sha256sum >/dev/null 2>&1 || command -v shasum >/dev/null 2>&1 || missing+=("sha256sum or shasum")
PY312=
for c in "${EP7_PYTHON:-}" python3.12 python3.13 python3.14 python3; do
  [ -n "$c" ] || continue
  command -v "$c" >/dev/null 2>&1 || continue
  if "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null; then PY312=$(command -v "$c"); break; fi
done
[ -n "$PY312" ] || missing+=("Python 3.12 or newer")
if [ ${#missing[@]} -gt 0 ]; then
  printf 'Missing: %s\n' "${missing[*]}" >&2
  if [ "$OS" = Darwin ]; then
    echo "On macOS: xcode-select --install ; brew install python@3.12 gnupg" >&2
  else
    echo "On Debian/Ubuntu: sudo apt install build-essential curl git python3 python3-venv gpgv xz-utils zlib1g-dev  (Python 3.12+ required)" >&2
  fi
  exit 1
fi
echo "python: $PY312 ($("$PY312" -V 2>&1))   toolchain prefix: $EP7_TOOLCHAIN"

# ---- 2. Python environment --------------------------------------------------------------------------------------------
step "Python environment (.venv)"
if [ -x .venv/bin/python ] && .venv/bin/python -c 'import numpy' 2>/dev/null; then
  echo ".venv: already set up"
else
  [ -x .venv/bin/python ] || "$PY312" -m venv .venv
  .venv/bin/python -m pip install --quiet --disable-pip-version-check -r requirements.txt
  .venv/bin/python -c 'import numpy; print("numpy", numpy.__version__)'
fi
export PYTHON=$PWD/.venv/bin/python

# ---- 3. submodule -----------------------------------------------------------------------------------------------------
step "Emulator harness submodule"
if [ ! -f external/oly_fw_analysis/tools/oly_container.py ]; then
  [ -e .git ] || { echo "This is not a git checkout: clone the repository with git (the submodule is needed)" >&2; exit 1; }
  git submodule update --init external/oly_fw_analysis
fi
echo "external/oly_fw_analysis: present"

# ---- 4. mn10300 binutils ----------------------------------------------------------------------------------------------
step "mn10300-elf binutils"
if [ -x "$EP7_TOOLCHAIN/mn10300/bin/mn10300-elf-as" ]; then
  echo "already installed in $EP7_TOOLCHAIN/mn10300/bin"
else
  echo "building GNU binutils 2.45 for mn10300-elf (a few minutes)"
  PREFIX=$EP7_TOOLCHAIN tools/setup_toolchain.sh
fi

# ---- 5. emulator ------------------------------------------------------------------------------------------------------
step "GNU MN103 simulator"
tools/setup_emulator.sh

# ---- 6. stock firmware ------------------------------------------------------------------------------------------------
step "Official E-P7 1.1 firmware"
tools/fetch_stock.sh
if [ -f analysis/ep7_1100/00_0100_406a0020.decoded.bin ] && (cd analysis/ep7_1100 && check_sums ../../docs/ep7_1100_components.sha256 >/dev/null 2>&1); then
  echo "analysis/ep7_1100: already decoded and verified"
else
  tools/decode_stock.sh
fi

printf '\nSetup done. Next:  make firmware\n'
