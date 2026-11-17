# Shared helpers for the tools/*.sh scripts (sourced, not run). Portable between macOS and Linux.
# sha256_of FILE        -> prints the SHA-256 hex digest
# check_sums LISTFILE   -> like `sha256sum -c LISTFILE` ("hash  path" lines, paths relative to the cwd)
# ncpu                  -> number of CPUs
sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1
  else shasum -a 256 "$1" | cut -d' ' -f1; fi
}
check_sums() {
  local bad=0 h f
  while read -r h f; do
    [ -z "$h" ] && continue
    if [ "$(sha256_of "$f")" = "$h" ]; then echo "$f: OK"; else echo "$f: FAILED" >&2; bad=1; fi
  done < "$1"
  return $bad
}
ncpu() { nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || getconf _NPROCESSORS_ONLN 2>/dev/null || echo 4; }
