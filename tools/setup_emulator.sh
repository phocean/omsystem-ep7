#!/usr/bin/env bash
# Build the pinned GNU MN103 simulator used by the verification steps (external/oly_fw_analysis/toolchains/mn103-gnu-build/penf-mn103).
# Downloads the pinned binutils-gdb commit from GNU's gitiles (needs network), verifies the CONTENT against the pinned git tree
# (the tar.gz itself is not byte-reproducible, see external/oly_fw_analysis/docs/tooling/EMULATOR.md), then builds it. Installs
# nothing outside external/oly_fw_analysis/toolchains/.
set -euo pipefail
cd "$(dirname "$0")/.."
. tools/common.sh
PYTHON=${PYTHON:-python3}
SUB=external/oly_fw_analysis
REV=87ffb882e0f4d73401a0746177ffabb8e8bbe4ac
TREE=059d50a3cc76bd13dc10f21023863674e6da515c
ARCHIVE_SHA=a5e7cd02f844bb2873c25e0ac8e9a5b50a72c3e8e6570a6b7821d2e4c21178ad
URL=https://gnu.googlesource.com/binutils-gdb/+archive/$REV.tar.gz
SRC=$SUB/toolchains/mn103-gnu-src
BIN=$SUB/toolchains/mn103-gnu-build/penf-mn103
CACHE=${EP7_CACHE:-$PWD/cache}
cleanup() { rm -rf "${W:-}" "${SHIM:-}"; }; trap cleanup EXIT

[ -f "$SUB/tools/build_mn103_emulator.py" ] || { echo "The submodule $SUB is missing: run  git submodule update --init" >&2; exit 1; }
if [ -x "$BIN" ]; then echo "emulator: already built ($BIN)"; exit 0; fi

if [ ! -f "$SRC/.penf-source.json" ]; then
  mkdir -p "$CACHE"; T="$CACHE/binutils-gdb-${REV:0:8}.tar.gz"
  [ -s "$T" ] || { echo "downloading $URL"; curl -fSL --retry 3 -o "$T.part" "$URL"; mv "$T.part" "$T"; }
  W=$(mktemp -d)
  mkdir "$W/src"; tar -xzf "$T" -C "$W/src"
  # verify the content: its git tree id must be the one of the pinned commit
  GOT=$(cd "$W/src" && git init -q . && git -c core.autocrlf=false -c core.attributesFile=/dev/null -c core.excludesFile=/dev/null add -f -A . && git write-tree)
  [ "$GOT" = "$TREE" ] || { echo "the downloaded source tree is $GOT, expected $TREE (pinned commit $REV): refusing to build" >&2; exit 1; }
  rm -rf "$W/src/.git"
  mkdir -p "$SRC"; cp -R "$W/src/." "$SRC/"
  cat > "$SRC/.penf-source.json" <<J
{
  "revision": "$REV",
  "archive_sha256": "$ARCHIVE_SHA",
  "note": "Extracted by tools/setup_emulator.sh from GNU gitiles; the content was verified against git tree $TREE of the pinned commit (the tar.gz bytes differ between downloads). archive_sha256 is the value the builder requires."
}
J
fi

# The simulator's generators use GNU sed scripts. BSD sed (macOS) rejects `{...;p}` ("extra characters at the end of p command")
# and leaves sim/common/modules.c empty. Use gsed if present, else a private shim that adds the ';' BSD sed wants before '}'.
SHIM=$(mktemp -d)
if ! sed --version >/dev/null 2>&1; then
  if command -v gsed >/dev/null 2>&1; then ln -s "$(command -v gsed)" "$SHIM/sed"
  else
    cat > "$SHIM/sed" <<'SH'
#!/bin/sh
n=$#; i=0
while [ "$i" -lt "$n" ]; do
  a=$1; shift
  case $a in *'p}'*) a=$(printf '%s' "$a" | /usr/bin/sed 's/p}/p;}/g');; esac
  set -- "$@" "$a"; i=$((i + 1))
done
exec /usr/bin/sed "$@"
SH
    chmod +x "$SHIM/sed"
  fi
fi
PATH="$SHIM:$PATH" "$PYTHON" "$SUB/tools/build_mn103_emulator.py" --jobs "$(ncpu)"
[ -x "$BIN" ] && echo "emulator: built ($BIN)"
