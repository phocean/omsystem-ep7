# firmware-ep7

A personal, minimal firmware for the **Olympus / OM PEN E-P7, firmware 1.1 only**. It is the stock 1.1 firmware plus a
small set of byte-level patches, built on your computer from OM's own download. It is derived from
[Caduceus for the E-P7](https://github.com/cakelesscoder/caduceus-ep7) (Apache-2.0): it keeps only what this
firmware uses and starts a new history (see [NOTICE](NOTICE)).

> [!WARNING]
> **Unofficial firmware. Flashing can brick your camera or lose data. Use at your own risk.**
> The patches are used by their author on one E-P7. Nothing is guaranteed on any other body or firmware version.
> This repository contains no OM firmware (it is never committed): the build downloads the official file and
> checks its SHA-256 before using it.

## What it changes

| Feature | Effect | Where |
|---|---|---|
| Front Profile Control lever | The last profile is applied directly. The profile list no longer opens when you move the lever; it stays reachable from a button assigned to it | `patches/lever_nomenu` |
| JPEG only on COLOR / MONO profiles | A COLOR or MONO profile never saves a RAW file, whatever the image-quality menu says. Always on, no option, nothing read from the SD card | `patches/jpeg_always`, [docs/JPEG_ALWAYS.md](docs/JPEG_ALWAYS.md) |
| LCD colour fix | Corrects the colour tint of the back screen (data table of the panel driver) | `patches/lcd_tint` |
| More button functions | Longer function lists for the Fn, REC, right and bottom buttons (Custom Menu > Button Function) | `patches/buttons`, `patches/omc_buttons`, `patches/btn_arrows`, [docs/OMC_FEATURES.md](docs/OMC_FEATURES.md) |
| Profile JPEG quality | In COLOR / MONO profiles the substituted JPEG is the first slot of the quality list (LSF) instead of the second (LF) | `patches/profile_lsf`, [docs/PROFILE_LSF.md](docs/PROFILE_LSF.md) |
| M/B dial | In Custom B > Dial function M/B the second choice becomes Shutter / Exposure comp (with ISO Auto it moves the auto ISO) | `patches/dial_expcomp`, [docs/DIAL_EXPCOMP.md](docs/DIAL_EXPCOMP.md) |
| Version label | Setup > Firmware shows "phocean" / "1.0" (display only) | `patches/fw_version` |

[docs/FINAL_BUILD.md](docs/FINAL_BUILD.md) lists every changed byte range and the expected hashes.
[docs/FIRMWARE_GUIDE.md](docs/FIRMWARE_GUIDE.md) explains how the firmware is built and the safety rules every patch follows.

## Build

Requirements: Python 3.12 or later (3.9 is too old for the emulator), a `mn10300-elf` toolchain
(`tools/setup_toolchain.sh`), the emulator submodule (`git submodule update --init`, see
`external/oly_fw_analysis/REPRODUCING.md`) and numpy for the LCD check.

```bash
tools/fetch_stock.sh        # downloads OM's firmware 1.1 and checks its SHA-256
tools/decode_stock.sh       # decodes it into analysis/ (not committed)
make final PYNP=/path/to/python-with-numpy
```

`make final` builds the package, runs every check (module verifiers, emulator tests, mutation tests, byte-for-byte
comparison with the stock) and refuses to write anything if a hash differs from the pinned one. Output:

- `out/final/DCOLYMP/E1429999.BIN`: the update file for the SD card;
- `out/final/restore/E1429999.BIN`: the stock firmware, to go back.

Nothing in this repository flashes a camera or writes to an SD card. See [docs/INSTALL.md](docs/INSTALL.md).

Other targets: `make minimal` (JPEG only + lever, nothing else), `make stock`, `make clean`.

## Credits and licence

Apache-2.0 (see [LICENSE](LICENSE)). Built on the work of cakelesscoder (Caduceus), and on fishcu's
`oly_fw_analysis` (emulator, GPL-3.0, used as a submodule only for verification). Details in [NOTICE](NOTICE).
"Olympus", "OM SYSTEM" and "PEN" are trademarks of their owners; this project is not affiliated with them.
