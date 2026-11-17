# Installing and going back

> [!WARNING]
> **Unofficial firmware, at your own risk.** Flashing can brick the camera. Only for a PEN E-P7 on firmware 1.1
> (Setup > Firmware). Use a fully charged battery. This repository holds no OM firmware: you build the update file yourself.

## 1. Build (on your computer)

Prerequisites: `git`, `curl`, `make`, a C compiler, `gpgv`, Python 3.12+ (see the README for the install commands).

```bash
make setup       # once, needs the network, about 10 to 20 minutes the first time (builds the toolchain and the emulator)
make firmware    # a few minutes: builds, verifies, prints the two files with their SHA-256
```

The two hashes printed must be the ones in `docs/FINAL_BUILD.md`. Keep `out/final/restore/E1429999.BIN` on your computer: it is the
stock firmware, to go back. To rebuild after a change, run `make firmware` again (`make setup` is not needed twice).
`make setup` can be re-run safely: finished steps are skipped. `EP7_TOOLCHAIN=/some/dir` moves the compiler install.

## 2. Flash

1. Copy `out/final/DCOLYMP/E1429999.BIN` to the root of the SD card as `DCOLYMP/E1429999.BIN`. The folder holds no other file.
2. Check the copy with `shasum -a 256` (same hash as the build).
3. Camera off, card in. Hold **OK** and switch on without releasing it.
4. The LED stays steady while the camera writes. Do not touch anything. A slow blink (about 2 Hz) means done; a fast blink means the file was rejected.
5. Switch off and on normally. Delete `DCOLYMP/E1429999.BIN` from the card.

## 3. Check

Open Custom Menu > Button Function (four rows), Setup > Firmware, Setup > Monitor Adjust, then take a photo in a COLOR profile:
it must produce a JPEG and no RAW. Then, in mode M, Custom Menu B > Dial function M/B: choose a pair and try the free dial
(no contact lens: ISO or exposure compensation; contact lens: aperture).

## 4. Go back

First, in Custom Menu B > Dial function M/B, choose **Shutter / FNo.** (the choice stock also has). Otherwise the stored
"Shutter / Exp comp" pair stays and the free dial does nothing in mode M on stock until you pick a stock choice again.

Copy `out/final/restore/E1429999.BIN` to the card as `DCOLYMP/E1429999.BIN` and flash it the same way. It writes the
stock firmware back (your camera settings are kept).
