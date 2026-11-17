# firmware-ep7

**A small, readable firmware for the Olympus / OM PEN E-P7 (firmware 1.1) that fixes the ergonomics the stock firmware gets wrong.**
It is the stock 1.1 firmware plus a few dozen byte-level patches, built on your own computer from OM's official download.
No firmware is distributed here. Derived from [Caduceus for the E-P7](https://github.com/cakelesscoder/caduceus-ep7)
(Apache-2.0); it keeps only what this firmware uses and starts a clean history (see [NOTICE](NOTICE)).

> [!WARNING]
> **Unofficial firmware. Flashing can brick your camera or lose data. Use at your own risk.**
> It has been used daily by its author on one E-P7 (firmware 1.1). Nothing is guaranteed on another body or firmware version.
> A tested way back to the stock firmware is built every time (see [Going back](#going-back)).

## What you get

| | |
|---|---|
| **Profile lever, no list** | Moving the front Profile Control lever applies the last profile directly. The list no longer pops up; it stays one button press away. |
| **JPEG only on COLOR / MONO profiles** | A COLOR or MONO profile never writes a RAW, whatever the quality menu says (it saves LSF, the best JPEG of your list). Normal modes keep RAW as usual. Always on, no option. |
| **Free dial in mode M, whatever your lens** | Custom Menu B > *Dial function M/B* now offers **Shutter / Exposure comp** and **Shutter / FNo.** With a lens with electronic contacts the free dial sets the aperture, as before. With a manual lens or adapter (where the FNo. dial does nothing) it sets the **ISO** (FNo. choice) or the **exposure compensation** (Exp comp choice). |
| **More button functions** | Longer function lists for the Fn, REC, right and bottom buttons, so you can put focus peaking, magnify and other functions where you want them. |
| **LCD colour fix** | Corrects the colour tint of the back screen. |
| **Version label** | Setup > Firmware shows `phocean 1.1`, so you can tell at a glance what is installed. |

Every change is a small module under `patches/` with its own document, builder and verifier. The full list of changed bytes
and the expected hashes are in [docs/FINAL_BUILD.md](docs/FINAL_BUILD.md).

## Quick start

Two commands. You need a Mac or Linux machine with `git`, `curl`, `make`, a C compiler, `gpgv` and Python 3.12+
(macOS: `xcode-select --install` and `brew install python@3.12 gnupg`; Debian/Ubuntu: `sudo apt install build-essential curl git python3 python3-venv gpgv xz-utils zlib1g-dev`).

```bash
git clone --recurse-submodules https://github.com/phocean/omsystem-ep7.git && cd omsystem-ep7
make setup       # once: Python environment with numpy, GNU toolchain and emulator (built from source), OM's firmware 1.1
make firmware    # builds the update file, runs every check, prints the two files and their hashes
```

`make setup` needs the network and takes a while the first time (it compiles GNU binutils and the MN103 simulator: roughly
10 to 20 minutes); running it again skips what is done. Nothing is installed outside this folder and `~/ep7fw-toolchains`
(change it with `EP7_TOOLCHAIN=/some/dir make setup`).

`make firmware` builds the package and runs every check (module verifiers, emulator tests on the real routines, mutation tests,
byte-for-byte comparison with the stock). It refuses to write anything if a hash differs from the pinned one. You get:

- `out/final/DCOLYMP/E1429999.BIN`: the update file for the SD card;
- `out/final/restore/E1429999.BIN`: the stock firmware, to go back.

Then follow [docs/INSTALL.md](docs/INSTALL.md): copy the file to `DCOLYMP/E1429999.BIN` on the card, hold **OK** while powering on,
slow LED blink = done. Nothing in this repository flashes a camera or touches an SD card.

## Going back

`out/final/restore/E1429999.BIN` is the exact stock firmware, flashed the same way. The restore path was tried on a real camera
before any patch was. Before restoring, pick *Shutter / FNo.* in Dial function M/B (details in [docs/INSTALL.md](docs/INSTALL.md)).

## How it is kept safe

Each patch follows the rules in [docs/FIRMWARE_GUIDE.md](docs/FIRMWARE_GUIDE.md): one feature group per flash, no write into the
loaded image, nothing that runs at boot, an emulator test of the real routines, and an independent security review of the
exact bytes before every flash. The one piece of added code (the dial logic, 76 bytes) is reached only by a dial turn, never at start-up.

What is **not** proven is listed in each patch document (for example, that the "contact lens" test behaves identically on every
adapter). Different lenses, adapters and bodies are exactly where help is welcome.

## Help wanted

If you try it, please open an issue with: camera serial prefix, firmware version shown in Setup > Firmware, the lenses/adapters
you used, and what you saw. Reports of failed flashes are as useful as successes. Please do not post OM firmware files.

## Credits and licence

Apache-2.0 (see [LICENSE](LICENSE)). Built on the work of cakelesscoder (Caduceus) and on fishcu's
[`oly_fw_analysis`](https://github.com/fishcu/oly_fw_analysis) (MN103 emulator, GPL-3.0, used as a submodule for verification only).
Details in [NOTICE](NOTICE). "Olympus", "OM SYSTEM" and "PEN" are trademarks of their owners; this project is not affiliated with them.
