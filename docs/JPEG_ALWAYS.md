# JPEG always on COLOR / MONO profiles (E-P7 1.1), definitive version

Build 2026-11-08, label `0.29j` (v0.29a base) or no label (stock base). Replaces the optional `patches/jpeg_only` (`docs/JPEG_ONLY.md`), which stays in the repo
unchanged. Not flashed, not camera-tested, not committed. Main CPU addresses (base `0x60020020`).
[V] = read from code or bytes. [S] = shown by the static / model checks. [E] = shown by the emulator run (`patches/jpeg_always/emu_verify.py`). [I] = inference.

## 1. Behaviour

Always on, no option, nothing read from the SD card. When the picture mode is COLOR (11) or MONO (12) (mode 6 is re-resolved through key `0x9d11`, as the capture does)
and the quality selector of the slot is neither 3 nor 4, the two reads of the "RAW in addition" flag of the capture path (`0x602a7f57` key `0x8231`, `0x602a7feb` key `0x5141`)
return 0: the capture record keeps file type 0 (JPEG) instead of 5 (JPEG + RAW). The quality setting in the menu is not changed. Any other picture mode, selector 3 / 4
(RAW only and the other special type: the capture never reads the flag there), and any other property key: the stock getter runs on the original frame, RAW unchanged.

The stub (`patches/jpeg_always/jo.s.in`, `jo_get`, 112 B at `0x601de540`, claim to `0x601de5d0`) is the `jpeg_only` stub minus the option: no call to `tbl_off` (`0x6055e7b6`),
no table, no `jo_prop` helper (the three property reads call the stock getter directly), no `movbu`. It calls nothing but the stock getter `0x6005e971`. No store, no
mul / div / setlb, no `fb` form, `.balign 4`, 3 zero bytes of padding after the last `ret` (unreachable). Registers: only `d0` differs from the stock call on the override path
(`d1`, `a0`, `a1`, `a2`, `a3`, `d2`, `d3`, `sp`, MDR, PSW equal) [E]. Stack: the deepest call is **12 B deeper than the stock getter call** (44 B below the site's SP, against 32 B for stock) [E];
`jpeg_only` measured 48 B (16 B deeper) with the same harness.

## 2. Two builds

| | `make jpeg_always` / `combo_always` | `make jpeg_always_stock` / `minimal` |
|---|---|---|
| Base | Caduceus release v0.29a (`releases/v0.29a/edits.json`) | the official stock 1.1 firmware, components `0x100` + `0x101` (0x101 = stock, never edited; 0x102 / 0x106 / 0x10e not included) |
| Command | `build.py releases/v0.29a/edits.json --out generated/jpeg_always/edits.json` | `build.py --base stock --out generated/jpeg_always_stock/edits.json` |
| Version label | `0.29j` (5 characters: the box on the Firmware screen is narrow and clipped `0.29jo1` to `29j`) | none (the label code belongs to v0.29a) |
| SD loader edit `0x605b7755` | kept (span[52] = 1, see section 4) | absent (there is no loader in stock) |
| EP7MOD on the card | the release's files (BUNDLES.BIN, LOOKS.BIN, MOVIE.BIN) | none, no card file at all |
| Package | `tools/fork_build.py build --base v0.29a --spec ...` | `tools/fork_build.py build --base stock --spec ... [--patch patches/lever_nomenu/edits.json]` |
| Bytes vs base | 120 (+1 with lever) | 118 (+1 with lever) |

`tools/fork_build.py --base stock` builds the package from the stock slices of components `0x100` and `0x101` + the spec, restore = the exact stock slices of both, no EP7MOD folder.
**Why 0x101 is included:** the updater rewrites every component of the package in full (docs/INSTALL.md), and the camera now flashed has `0x101` (display resources) modified by Caduceus v0.29a (15 edits). A `0x100`-only package would leave that modified `0x101` next to a stock main program, a state never tested. Including `0x101` as an unedited stock payload puts it back to stock (precedent: `releases/test1-rec-limit`, components 0x100 + 0x101, edits on 0x100 only). Checked byte by byte against the stock file: the `0x101` payload of the package is identical to stock (0 bytes differ), the header is identical, 0x100 differs by 118 bytes (119 with lever_nomenu), the restore file equals the stock slices of both components. It refuses any edit
that is not a main-CPU edit inside the jpeg_always stub range, the two site rel32 operands, or the lever_nomenu byte (`0x60cd4a0a`), and any edit on `0x101`. Nothing in the stock build depends on code added by a release:
the stub calls only the stock getter, the sites are the stock `call 0x6005e971,[d2,d3],12` (checked), and the stub sits in section 1 while the sites are in section 2 (loaded after section 1) [S].
The claim range is the dead EVF gamma table `0x601de53c..0x601de63c`: on the stock image every byte of `0x601de540..0x601de5cf` is the identity ramp, the only absolute reference to the table is the
step-table word `0x601e3c14` (= `0x601de53c`), nothing references the claim or jumps / calls into the table (`0x601e3c18` holds `0x601de63c`, the end of the table, which is the start of the next one, not a reference into it) [V].

## 3. What stays true from the safety review of jpeg_only (R1 to R7)

- **R1. RAW is possible by other paths, not examined**: burst, HDR, bracketing, photo during video, the function-button "RAW" action (14), RAW development in playback (`0x60c67633`, key `0x8231`, left stock on purpose).
  "JPEG always" only changes the two capture-record reads. A RAW file can still appear on those paths. Check with the camera before relying on it.
- **R2. The message sites are optional and off by default.** The settings-message reads (`0x60554e76`, `0x60554e87`, `--msg`) and the view-count estimator (`0x6061e079`, `--estimator`) are not redirected: the consumer of message byte `+62` is not
  identified. The default build is the two capture sites only. Without them the RAW file may still be written if the message path creates it ([I], not proven either way).
- **R3. The screen still says RAW.** The menu, the INFO display and the remaining-shots counter (sid-based estimators `0x602e7ca9`, `0x602ece31`, `0x602eefbd`, `0x602f0621`, `0x60889ee5`) still count a RAW file that is not written. The counter is conservative.
- **R4. Going back to an older firmware.** Any firmware before 0.29jo1 rejects a BUNDLES.BIN with +52 = 1 as a whole file. Before going back, set +52 to 0 (section 4).
- **R5. Not proven without the camera:** that the capture record path is the only one that creates the ORF; MDR and PSW equality on the real camera (equal in the emulator [E]); the playback display of a file the menu says is RAW.
- **R6. Stack.** 12 B deeper than the stock getter call [E]; the real margin of the tasks that run the two sites is unknown.
- **R7. Control Panel.** See section 6.

## 4. Migration: BUNDLES.BIN with +52 = 1 (critical)

The camera currently flashed is v0.29a + lever_nomenu + jpeg_only. Its card has `EP7MOD/BUNDLES.BIN` with byte +52 of slot 0 = 1. The loader of that firmware accepts +52 in {0, 1}
(per-byte span table at `0x605b7721`, entry +52 = `0x605b7755`); a loader that finds a byte out of range rejects the **whole file** and every profile falls back to the flashed table (the saved looks are lost on the next save).

**The v0.29a build keeps that loader edit**: span[52] = 1 and lo[52] = 0 in the patched image, so the new firmware still accepts +52 = 0 and +52 = 1, and the file is read as before. The value is ignored: nothing reads it.
Proof: `verify.py` part L prints `span[52] (0x605b7755) = 1, lo[52] (0x605b7715) = 0` and fails otherwise [S]; the diff of the `combo_always` image against the `combo` image shows no byte at `0x605b7755` (both 1) [S].
The Control Panel keeps working with its checkbox on or off: the written file loads whatever +52 is.

**The stock build has no loader at all** (no EP7MOD code): the card files are never read, so BUNDLES.BIN is neither accepted nor rejected, just ignored. Nothing on the card is touched. The looks, Film menu, editor and every other Caduceus feature are gone with that firmware.
Flashing it from the current firmware drops them; the file survives on the card for a later Caduceus build.

Do not put a file with +52 = 2 or more on a v0.29a build (rejected whole).

## 5. Checks and how to run them

```
export EP7_STOCK_MAIN=analysis/ep7_1100/00_0100_406a0020.decoded.bin
python3 -I patches/jpeg_always/build.py releases/v0.29a/edits.json --out generated/jpeg_always/edits.json     # [--version 0.29j] [--msg] [--estimator]
python3 -I patches/jpeg_always/verify.py releases/v0.29a/edits.json generated/jpeg_always/edits.json
python3 -I patches/jpeg_always/mutate.py releases/v0.29a/edits.json generated/jpeg_always/edits.json
python3 -I patches/jpeg_always/emu_verify.py                                    # about 1.5 min on 10 cores; --base stock for the stock image
python3 -I patches/jpeg_always/build.py --base stock --out generated/jpeg_always_stock/edits.json
python3 -I patches/jpeg_always/verify.py stock generated/jpeg_always_stock/edits.json
python3 -I patches/jpeg_always/mutate.py stock generated/jpeg_always_stock/edits.json
```

`build.py` refuses on: a site that is not `call 0x6005e971,[d2,d3],12` with key load, `mov 0,a0`, `clr d1` in front; a branch into a site's operand; a claim that overlaps an edit or is referenced; a stub that
calls anything but the stock getter, reads memory, stores, or uses mul / div / setlb / `fb` forms; misaligned code; a section order where a site can run before the stub; a v0.29a base whose loader span for +52 is not 0.
`verify.py`: also CODE_SPACE_MAP and every `releases/*/edits.json` / `patches/*/edits.json` against this patch's edits (jpeg_only shares the claim on purpose and is skipped), the diff of the patched image against the base (only our bytes),
the migration check (L), and a model run over the real assembled bytes (keys x idx x getter d1 behaviour x selector x mode x mode 6 x flag x other selector; no option, no accessor call allowed).
`mutate.py`: 26 single-byte mutants of the stub, plus (v0.29a build) one migration mutant, the loader span[52] put back to 0: 27/27 killed on v0.29a, 26/26 on stock. `emu_verify.py`: the real capture-record population function `0x602a7ea0`, the real getter, on the base image vs base + stub, over mode x selector x RAW flag x slot-2 enable matrices,
foreign keys and idx, register comparison at the real site return addresses, stack depth, and 16 emulator mutants; no table, no SD handle and no loaded bundle is mapped, so any access to them would fault.

## 6. Control Panel (not touched)

Nothing was added to `webapp/`. What it would need:
- **Remove**: the "JPEG only on COLOR and MONO profiles" checkbox, `Pack.jpegOnly`, the pack-file key `jpeg_only`, its sharecode field, the `[52, 1, 0, 1]` FIELDS entry, the "v0.29jo1" Firmware level, `tools/ep7_bundles_bin.py`'s `"jpeg_only"` key and `tools/ep7_jpeg_only_toggle.py` (if present in the checkout). The feature has no setting any more.
- **Keep**: the export may keep writing +52 = 0 or 1, both are accepted by the v0.29a build with this patch. The safest is to always write 0 (older loaders then accept the file too, R4) and to keep `checkBundlesBin` accepting 0..1.
- The Firmware level for this release must not gate +52 (a file with +52 = 1 stays valid).

## 7. Not verified

Camera behaviour, ORF absence in practice, burst / HDR / bracketing paths, the playback display, the real stack margin, the screen label rendering of `0.29j` on the camera, whether the camera's updater accepts a stock-based package (a package of this shape, components 0x100 + 0x101, was not flashed by us from a Caduceus-flashed camera), and what the camera does with Caduceus-written settings that remain in its flash when it boots a stock-based build.


## Expected hashes of the minimal package (`make minimal`)

Built from the official stock 1.1 (SHA-256 9d161012...eaeb) with `patches/jpeg_always` and `patches/lever_nomenu`; 119 bytes differ from the stock,
all in component 0x100; component 0x101 is the stock one.

- `out/minimal/DCOLYMP/E1429999.BIN`  0812d765619a48a47cafc3fbb80987abd186de9e4c3dc8d44572f3f32c6e3882
- `out/minimal/restore/E1429999.BIN`  963f4dfe560e29216862c96284c92225f49977fd831a2ed60fa3ebbddf6d2327 (the stock slice of both components)

Check the file on the card against the first hash before flashing. Run the emulator test from the main checkout with `make jpeg_always_stock_emu`.
