# Final firmware: stock 1.1 + JPEG always + lever + LCD colour fix + more button functions

Build 2026-11-08 (`make final`). Not flashed, not camera-tested in this combination, not committed. Main CPU addresses (base `0x60020020`).
[V] = read from code or bytes. [S] = shown by a static check. [E] = shown by the emulator run. [I] = inference.

This is `make minimal` (stock + `patches/jpeg_always` + `patches/lever_nomenu`, `docs/JPEG_ALWAYS.md`) plus two Caduceus v0.29a features:

1. **LCD colour fix** (`patches/lcd_tint`, README "LCD colour fix"): +8 % green by default, Monitor Adjust colour slider = green/magenta -7..+7. Display only.
2. **More button functions** (`patches/omc_buttons` + `patches/btn_arrows`, `docs/BUTTONS.md`): REC and Fn gain AF Home, RAW, Test picture, Keystone, HDR, BKT, ISO/WB, WB/ISO, Multi Function, Level, IS mode;
   the right and down arrow keys can be set in Custom Menu > Button Function (Flash, Drive, Exp comp, Touch lock, Electronic zoom, Accessories, MF, ISO/WB, WB/ISO, Peaking, Level, Tele-converter, RAW, Off); the right row is titled "Right Fn".

**Excluded: everything else of Caduceus** (looks, film menu, look editor, EP7MOD loader and files, Blacks/Whites, grain, sharpening/NR, mono, movie colour, aspect XPan/21:9 and its icons, vertical video, recording limit, page order, the firmware version label, ...).
Components `0x100` + `0x101`; `0x101` is the unedited stock payload. No EP7MOD folder, no card file at all.

## 1. Modules, ranges, bytes

The build is refused for any byte outside the ranges below (`tools/fork_build.py` `STOCK_MODULES`, `--module NAME`), for overlapping ranges, for a declared module without an edit,
and for an edit whose `source` names another module. `patches/final/build.py` re-derives the ranges from each module's own builder and refuses if they differ. Edits to `0x101` are accepted
only inside a declared `0x101` range; none is declared. Registered in `docs/CODE_SPACE_MAP.md` ("Final firmware").

| Module | Builder | Edits | Written bytes | Bytes that differ from the stock | Ranges (end exclusive) |
|---|---|---:|---:|---:|---|
| jpeg_always | `patches/jpeg_always/build.py --base stock` | 3 | 120 | 118 | stub 0x601de540-0x601de5b0 (claim to 0x601de5d0), rel32 0x602a7f58-5c, 0x602a7fec-f0 |
| lever_nomenu | `patches/lever_nomenu/edits.json` | 1 | 1 | 1 | 0x60cd4a0a |
| lcd_tint | `patches/lcd_tint/build.py` `edits(8, 16)` | 4 | 5853 | 513 | table 0x602355de-0x60236cb8 (225 rows x 26 B), G bytes 0x602353ee, 0x602354b2, 0x60236d2a |
| omc_buttons | `patches/buttons/build.py` `edits()` | 7 | 64 | 40 | list 0x604cae3c-0x604cae6a (23 codes); records 0x604cda14 (2), 0x604cda20 (4), 0x604cda28 (2), 0x604cda34 (4), 0x604cda3c (2), 0x604cdae8 (4) |
| btn_arrows | `patches/btn_arrows/build.py` `apply(version=None)` | 10 | 71 | 44 | list 0x604cb00e-0x604cb02e (14 codes); records 0x604cdadc (2), 0x604cdaf0 (2); rows 0x61242fe8-0x61242ff0; text "Right Fn" 0x61242ff0-0x61242ff9; mode-42 record 0x6115056c-0x61150572; item records 0x611bf7c8 (2), 0x611bf7cc (4), 0x611ccf34 (2), 0x611ccf38 (4) |
| fw_version | `patches/fw_version/build.py` `apply(spec, "1.0", "phocean")` | 5 | 64 | 54 | setter calls 0x60d7f271, 0x60d7f2cd (7 B each); `fw_val` 0x601e1c40 (34 B, dead EVF table); row descriptor 0x6115d5e8 (8 B); text "phocean" 0x61242fc0 (8 B). Display only: Setup > Firmware, Body row shows title "phocean" and value "1.0" instead of "Body" / "1.1" |
| dial_expcomp | `patches/dial_expcomp/edits.json` | 2 | 3 | 2 | list byte 0x604bb480 (03 -> 02), label id 0x611d6d56 (93 02 -> 92 02). Custom B > Dial function M/B: second choice {Shutter, FNo.} becomes {Shutter, Exposure comp}, the same entry the shutter-priority record carries. See [DIAL_EXPCOMP.md](DIAL_EXPCOMP.md) |
| profile_lsf | `patches/profile_lsf/edits.json` | 1 | 1 | 1 | result byte 0x6043c24e (0f -> 0e) of the quality dependency rules: in a profile, "RAW only" is rewritten to JPEG slot 1 + RAW (the first quality slot, LSF here) instead of slot 2 (LF). See [PROFILE_LSF.md](PROFILE_LSF.md) |
| **Total** | | **33** | **6177** | **773** (0x100) + **0** (0x101) | |

(Written bytes count every byte of an edit; "differ" counts only the bytes whose value changes.)

Code: only the jpeg_always stub (112 B, section 1, dead EVF gamma table) is code. Every other module is data edited in place (lists, record fields, a table, one opcode byte for the lever) or text/list words in the
section 6 FF tail (0x61242fe8-0x61242ff9, section 6 load end 0x61243000, all FF in the stock [V]). **No store in the loaded image, no new code, no relocated table, no `.balign` needed** (the one 4-byte-aligned datum, the row list at 0x61242fe8, is aligned [S]).

### Where each module reads its inputs (what stays stock)

- LCD: the panel routine `0x60184360` builds a 70-byte SPI command from the 225-row table; rows words 0..3 -> `0xd9` [mode, R, G, B]. Only these bytes change; brightness words, the ISP, JPEG, movie encoder and HDMI never read them [S, `tools/ep7_verify_lcd_tint.py` X].
- Buttons: the allowed codes come from the static validator records (sids 47/48/49 = REC/Fn/AEL buttons, 51 = down arrow, 53 = right arrow); the press dispatcher `0x60cc872f` maps key -> sid -> value -> function table `0x60f38af8`; labels come from the stock tables
  `0x611baf8c` (44 values) and `0x611d78cc` (Button Function entries); every added code already exists in a stock list of another E-P7 button, has an action and a label [S, `patches/buttons/build.py` static checks, all PASS].

## 2. Hidden dependencies looked for, and how each was treated

| Candidate | Finding | Treatment |
|---|---|---|
| `0x101` strings / icons for the new button labels | None needed [V]. The 23 + 14 codes are labelled by stock entries (string ids and icon ids that the stock lists already use); v0.29a has no `0x101` edit for buttons (its 15 `0x101` edits are aspect icons and SCP cells). | `0x101` stays the stock payload. A label whose stock string were missing would show an empty cell, not crash [I]. |
| Version label (`patches/fw_version`) | `omc_buttons.apply()` and `btn_arrows.apply()` call it and require a v0.28 base. It is Caduceus-only (code at 0x601e1c40, text at 0x61242fc0). | Not used for the Caduceus label. The final calls the same helpers on the stock image (`BT.edits`, `BA.apply(version=None)`) and adds its own label with `patches/fw_version` (title "phocean", value "1.0"; change with `patches/final/build.py --label/--version`, then update the pinned hashes). The `L` check of `omc_buttons/verify.py` (label "0.28o1") does not apply and is replaced by `patches/fw_version/verify.py`. |
| `btn_arrows` needs the `omc_buttons` arrow edits | `BA.apply()` replaces two omc edits in place and needs `spec['buttons']['dpad_at']`. | `patches/final/build.py` builds the omc edits first from the stock, then runs `BA.apply()`; the result is **byte-identical to v0.29a** (same address, same `expect`, same `new`) for all 4 + 7 + 10 edits [S]. |
| Section 6 FF tail shared with other patches | In v0.29a the tail 0x61242d00-0x61243000 also holds the film-menu hooks, the 270 list and the "Caduceus" text; btn_arrows takes 0x61242fe8-0x61242ff9. | Alone in the final; stock FF, no stock word points into it, guard 0x61242ff9-0x61243000 stays FF [S]. |
| Film-menu label-builder hooks (`0x60df255f`, `0x60df25dc`) | In v0.29a they sit on the kind-4 label path (jmp to hooks at 0x61242d10/e10, replay of stock for any non-film row). "Right Fn" is a **kind 5** label, so it is not routed through them. The 23 + 14 button labels are kind 3/4 and fall through the hooks to the stock path. | The final has the stock builders. Window check W lists them as the only (expected) differences with v0.29a next to the setting 270 record. |
| `kind 5` text on the sid 53 item records | `kind 5` is a stock kind (Artist/Copyright and Lens Info rows use it, `docs/LOOK_MENUS.md`). The Button Function screen with kind 5 was only run in Caduceus builds. | Same bytes as v0.29a. Whether the stock row builder behaves the same without the Caduceus hooks is [I] (they replay the stock path); camera test needed. |
| Setting 270 validator record (0x604cec18) | v0.29a moves the list of the aspect setting 270; it sits in the validator table the buttons use. | Not in the final (stock record). Sids 47-53 and their neighbours list the same values as v0.29a [E]. |
| Stored values written by other Caduceus features | Settings are stored by the camera, not by the firmware. Values outside the stock validator range (aspect XPan / 21:9, Caduceus-only slots) can remain stored. | **Not examined.** v0.29a boots back to 4:3 at each power-on (README). If anything looks wrong after the flash, reset the camera settings. |
| Shared `.data` image (LCD table) | `0x602355de` is in the resident image (outside the nine loaded sections), `.data` init image copied to 0x61f9d31e at boot; only references: 0x601843fa (table) and 0x60184368 (template). | Same as v0.20 / v0.29a; checked X (all 26 words that point into the edited `.data` sit in the panel driver or are call opcodes). |

No patch of the five needed an edit of an other Caduceus patch: every dependency above was absorbed by calling the module's own helpers on the stock image. **Nothing had to be cut.**

## 3. Checks (`make final`, `make final_emu`) and their results

All results below were produced on the final image of this build (not on the v0.29a image).

```
make final MAIN=<main checkout> PYNP=<python with numpy>      # build + verify + out/final ; about 5 minutes
make final_emu MAIN=<main checkout>                           # jpeg_always emulator test inside the final image, minutes
```
`MAIN` is the checkout that holds `external/oly_fw_analysis` (the emulator engine); default = this directory. `PYNP` must be a Python with numpy (`tools/ep7_verify_lcd_tint.py`, `patches/final/verify.py`).

| Step | Tool | Result |
|---|---|---|
| jpeg_always on the stock | `patches/jpeg_always/verify.py stock`: S 47 instructions, D 118 bytes differ, M 13728 model runs | PASS |
| jpeg_always mutants | `patches/jpeg_always/mutate.py stock` | 26/26 killed |
| final spec | `patches/final/build.py`: stock `expect` of every edit, no overlap, ranges == `STOCK_MODULES`, sec-6 tail FF, == v0.29a edits | PASS (25 edits) |
| package | `tools/fork_build.py build --base stock ... --expect-sha256 --expect-restore-sha256` | written, hashes pinned |
| buttons | `tools/ep7_buttons_verify.py` on the final spec: S, V (5 sids + 24 others), N, A, M mutations | PASS x5 |
| arrows | `patches/btn_arrows/verify.py` (base = final without btn_arrows): P (44 bytes differ, none stray), Y, R, T | ALL PASS |
| LCD | `tools/ep7_verify_lcd_tint.py` (base = final without lcd_tint): D, T (225 rows exact), X, E (45 emulator cases) | pass: true |
| lever | `patches/lever_nomenu/verify.py` | RESULT PASS (incl. 2 mutants detected) |
| final | `patches/final/verify.py`: P, D, O (omc checks V 29/29, N 5/5, A 28/28, Y 7/7, anti-brick), W (18 windows, 16 bytes differ from v0.29a, all expected), C (25 ranges vs 380 v0.29a edits: no overlap), X (17 sids listing, dial stepping, 27 code -> action + key kinds, 45 LCD SPI buffers: final == v0.29a) | ALL PASS |
| perimeter | 14 negative tests of `fork_build.py` (stray byte, byte next to a list, byte after the claim, 0x101 edit, wrong source, unused module, unknown / duplicate module, spec/CLI mismatch, wrong pinned hash, no `modules` with the default pair, overlapping ranges) | all refused, nothing written |
| emulator, jpeg_always inside the final image | `make final_emu` (`emu_verify.py --base final`: the real capture-record function, base = final without jpeg_always vs the whole final; 118 bytes differ) | RESULT PASS (717 cases, 0 failing); 16/16 mutants killed |

`patches/omc_buttons/verify.py` itself needs a v0.28 base and the label check; its V/N/A/Y/P checks are re-run by `patches/final/verify.py` on the final image. `tools/ep7_mc_ui_verify.py` is a mono-colour verifier: not relevant.

## 4. Hashes

Stock `OLY_E_142_1100_0000_0000.BIN`: `9d1610124ad98f6edae4540182205f06c9c703d9033ef0c4f19847193f95eaeb`.

| File | SHA-256 |
|---|---|
| `out/final/DCOLYMP/E1429999.BIN` (52,428,800 B) | `e6fe5c8de2e2282b5951cbf13fc427702bcf8569896045c29b7bca4fd6e7e250` |
| `out/final/restore/E1429999.BIN` (the stock slice of 0x100 + 0x101; same file as `out/minimal/restore`) | `963f4dfe560e29216862c96284c92225f49977fd831a2ed60fa3ebbddf6d2327` |
| decoded 0x100 payload of the final | `6b48fc6769a70249685d3dd59976b9fd8f983c9481c592148159a527763d0fc5` |
| decoded 0x100 payload of the stock | `5dd9af164b4590c7e82f6905c919b3cc450bb58f2d5742ab2a0e3a4eb2e26190` |
| decoded 0x101 payload (final == stock) | `8606cb90e06b67aee31a1b4319b585905b66e4e3ee29c903bd328aa33b362868` |

The package hash is pinned in the Makefile (`FINAL_SHA`, `FINAL_RESTORE_SHA`): a different build is refused and nothing is written. The final differs from `out/minimal` (`0812d765...3882`) by 654 bytes of 0x100; 0x101 is identical.
Check the file on the card against the first hash before flashing.

## 5. Risks and what was not established

- **Not camera-tested in this combination** (stock + jpeg_always + lever + lcd_tint + buttons). The README tags the two features "New in v0.20" and "New in v0.29", not "Camera-tested": the arrow rows were camera-run at b4 (`docs/BUTTONS.md` 4d), and b5 / v0.29 is a beta. The LCD patch was released in v0.20; CHANGELOG records no camera defect.
- **What changes when the rest of Caduceus is removed.** Sections: no section gets new code (the jpeg stub is in section 1, loaded before the section 2 sites; the other modules are data). Tables: none is relocated; the 23-code and 14-code lists are in place, the old lists beyond them are unreferenced stock bytes.
  Label hooks and the Caduceus version label are gone (the fork's own label "phocean 1.0" replaces it). `0x101` goes back to stock. No SD loader, so EP7MOD is ignored (not touched). The film menu / looks / editor are gone. Behaviour of the Button Function screen without the Caduceus hooks on the same screen is [I] (see section 2).
- **Emulator evidence is for the data paths** (validator, stepping, dispatcher function table, LCD SPI buffer). The row list, the "Right Fn" text and the kind-5 item path (UI drawing) are checked as bytes and as table reads, not as a drawn screen.
- **RAW is still possible on paths jpeg_always does not cover** (R1-R3 of `docs/JPEG_ALWAYS.md`). Assigning a button to RAW (code 22) is a deliberate RAW action; it is one of the functions this build offers.
- **Flash path.** The camera currently flashed has Caduceus v0.29a (+ lever + jpeg_only) and a modified `0x101`. This package writes `0x100` and `0x101` in full (`0x101` = stock). Whether the updater accepts a stock-based package from a Caduceus-flashed camera was not tried by us (`docs/JPEG_ALWAYS.md` section 7). One change per flash, restore file ready (`docs/INSTALL.md`).
- Old settings: Caduceus BUNDLES.BIN / LOOKS.BIN on the card are not read by this firmware. Settings stored by the camera that only Caduceus could set are not checked (section 2).
- Not run here: `patches/jpeg_always/emu_verify.py --base stock` on the stock-only image (unchanged, `make jpeg_always_stock_emu`).
