# M-mode dial: FNo. becomes ISO without a contact lens (E-P7 1.1, `patches/dial_iso`)

In mode M, when a free dial is assigned to **FNo.** (dial function 3) and **no lens with electronic contacts is connected**
(manual lens or adapter: the aperture is not electronic, so the FNo. dial does nothing useful), the dial function becomes
**ISO** (6): stock then handles the rotation through its own ISO-direct branch, as it does for the ISO shortcut
(screen transition `REQ_ISO_DIRECT_MAIN` / `SUB_DIAL`, then `0x60cde346(function, counter)`). With a contact lens
connected nothing changes: the behaviour is exactly stock. Nothing else is touched: no menu, no setting, no data, no store.

## What changes (2 edits, 69 bytes; `patches/dial_iso/edits.json`, built by `patches/dial_iso/build.py`)

| Address | Stock | Patched | Meaning |
|---|---|---|---|
| 0x60cdc837 (9 B, section 6) | `f1 e3 dd b0 c3 fe ff c0 08` = `mov d0,a3 ; call 0x60cc8be9,[d2,d3],8` | `dc c9 40 53 ff cb cb cb cb` = `jmp 0x60210900 ; nop x4` | in the dial routine 0x60cdc82c, right after `call 0x60cc8b23` (d0 = dial function code). Resume at 0x60cdc840 (`mov d0,(32,sp)`) |
| 0x60210900 (60 B, section 1) | 60 x FF | `dl_fn` (patches/dial_iso/dial_iso.s.in) | replays the two displaced instructions, with a3/d0 possibly changed |

Ranges for `tools/fork_build.py` `STOCK_MODULES['dial_iso']['0x100']` (printed by build.py, asserted by verify.py):
**stub (0x60210900, 0x6021093c)**, **hook (0x60cdc837, 0x60cdc840)**. Edits carry `"source": "patches/dial_iso"`.

```
60210900  mov d0,a3                       displaced
60210902  cmp 3,d0 ; bne 0x60210930       not FNo.: stock (d0 = fn)
60210906  mov 109,d0 ; call 0x60ccf9f3,[d2,a2],24      mode key: sid 109 ...
6021090f  cmp 0,d0 ; bne 0x6021091c
60210913  mov 24,d0 ; call 0x60ccf9f3,[d2,a2],24       ... else sid 24
6021091c  cmp 6,d0 ; bne 0x6021092e                    6 = M
60210920  call 0x602ea74c,[d2],28 ; exthu d0
60210928  cmp 0,d0 ; bne 0x6021092e                    != 0: contact lens connected -> stock
6021092c  mov 6,a3                         ISO
6021092e  mov a3,d0
60210930  call 0x60cc8be9,[d2,d3],8        displaced call (d0 = a3 on every path)
60210937  jmp 0x60cdc840
```

The routine keeps the function code in a3 for the rest of its work, and gives it in d0 to the rule lookup 0x60cc8be9. The stub puts the
same value in both, so the rule and the ISO-direct branch (`cmp 6,a3` at 0x60cdc976) agree. Result for FNo. + M + no contact lens: the routine
runs exactly as stock would for a dial assigned to ISO.

Settings getter: the routine's own `call 0x60ccf9f3,[d2,a2],24` (sid in d0, used at 0x60cdc876 / 0x60cdc893) is reused with the same frame. The
`0x602cbc0a` of FIRMWARE_GUIDE section 3 ("getter by sid") is a different function (`ret [],4`, key path) and is NOT used. `0x602ea74c` has
18 call sites in stock (the frame `[d2],28` is the one its return `ret [d2],28` at 0x602ea78e ends with).

## Safety analysis

* **Free zone (recomputed from the stock decoded main)**: 0x602108ec..0x60211000 is all FF (0x602108eb is the last non-FF byte); claim
  0x60210900..0x6021093c, 20 B of FF in front, 0x6021093c.. FF behind. No abs32 word (cached 0x6, uncached 0xa, flash-logical 0x4, flash-uncached 0x8
  alias; any byte offset), no jmp/call d32/d16, calls, or bcc d8 points into the claim; the only hit in the 16-B guards is a mid-instruction false
  positive pinned in build.py (0x6086f774 `f0 08 21 60` = `mov (a0),a2 ; add 96,a1`, value 0x602108f0). The known false positive 0x605985c3 (0x40890992 =
  0x60210992 in the flash-logical alias) is outside the claim.
* **Hook**: the 9 bytes are two whole instructions of the routine (checked on the disassembly of 0x60cdc82c..0x60cdcbde). No branch of the routine, no
  jmp/call encoding elsewhere and no abs32 word lands in 0x60cdc838..0x60cdc83f (one bcc-looking byte pair at 0x60cdc83b is inside the displaced call itself).
  Resume 0x60cdc840 is a whole instruction.
* **Load order** (FIRMWARE_GUIDE section 2): stub in section 1 (loaded first), hook in section 6 (loaded later), so the hook never runs before the stub exists.
  The gate `0xa272e420 & 0x1ff` of section 9 / section 5 hooks is not needed: the hook is in the dial routine, entered from a dial rotation event of the
  UI/dial task; no code of the patch runs at boot, and the stub is only reached through the hook. Both parts are written by the same package flash.
* **Registers**: the stub writes a3 and d0 directly. Through the calls it leaves d1, a0, a1 scratch (the displaced call to the rule leaves them scratch
  too: the rule overwrites d1/a0, and nothing after 0x60cdc840 reads d1/a0/a1 before writing them). d2, d3, a2 are preserved by the callee
  frames (`[d2,a2]`, `[d2]`, `[d2,d3]`); build.py checks that the bodies of 0x60ccf9f3 and 0x602ea74c do not write d3/a3 (nor a2 for the latter).
  **MDR**: `call` sets MDR to its return address (leaf `retf` returns through it). At the resume point MDR is 0x60210937 (stub) instead of 0x60cdc840
  (stock), and the routine's slot (0,sp) holds the same return address. The first instruction after the resume point that touches MDR is the `call` at
  0x60cdc848, which overwrites both before anything reads them; the emulator shows MDR identical at the end of the routine (E3). The stub uses no
  mul/div/ext (nothing reads MDR as data), no setlb, no fb form.
* **Stack**: the stub has no frame of its own. Its three calls are made at the routine's own sp (the same sp as the stock calls to 0x60ccf9f3 at
  0x60cdc876 / 0x60cdc893, and the displaced call): the getter adds no depth over stock. 0x602ea74c uses a 28-B frame plus its own callees
  (0x602c1291 12 B, 0x602c12f4 32 B, 0x601f0120 4 B); the routine already makes calls of 92 B (0x60cce3dc) and 64 B (0x60ccac3e) at the same sp,
  but the full depth below 0x602ea74c was NOT measured. sp is identical at exit in every emulator case.
* No store, no data, no table, no read of memory by the stub itself (build.py audit). Size 60 B = the claim.

## Checks (`patches/dial_iso/verify.py`, exit 0 = everything passes; ~30 s)

    EP7_MAIN_REPO=$PWD PYTHONPATH=$PWD/external/oly_fw_analysis/tools python3 -I patches/dial_iso/verify.py [edits.json] [--decoded PATCHED_MAIN]

* **P**: package (stock + edits = patched, only the 69 module bytes differ, edits.json is what build.py makes now, optional decoded payload compare).
* **E1**: the REAL routine 0x60cdc82c with the REAL rule 0x60cc8be9 and the real ISO helpers 0x60cdda80 / 0x60cddaec / 0x60cde346; other callees stubbed at
  their own address with the frame of their call site; the image is read-only. 256 cases = 2 events x counter +-1 x mode key {3,4,5,6} x lens {0,1} x d2
  {9,12,13,19} x 0x60ceca1d {0,1}, function 3. Outside the target (key 6 and lens 0) the 224 cases equal stock (calls, return, (32,a2), (192,a2),
  (272/276,a2), sp, all registers, MDR, stack above sp). The 32 target cases: a3 = 6, the rule is called with 6; with the gate passed (d2 in 9/12/13)
  `0x60cde346(6, +-counter)`, (32,a2) = 215 (main) / 216 (sub), (192,a2) = 0x5704, return 0.
* **E2**: 600 random combinations (function 2..9, sid 109 / 24 / 26, lens, rule 75, 0x60cd20e9, card write, (188,a2) = 0x5101, d2 states, event,
  counter, 0x60ceca1d): patched(fn) == stock(fn'), fn' = 6 if (fn == 3, key == 6, lens == 0) else fn, key = sid 109 else sid 24, at the resume point
  and at the end.
* **E3**: MDR (above).
* **M**: 13 mutants (lens polarity, key 6 -> 5, fn 3 -> 4, ISO 6 -> 9, hook shifted by 2, no resume jmp, sid 109 -> 108, sid 24 fallback dropped,
  lens / fn tests dropped, d0 restore dropped, ISO only in d0, sid 24 only) are all detected.

## Behaviour in the emulator that you should know

With the ISO-direct guards passed, `+1` calls 0x60ccf908 and `-1` calls 0x60ccf94a. When a guard fails the generic path (stock's own, same as a dial assigned
to ISO) runs instead, and it is **reversed**: `+1` calls 0x60ccf94a (and 0x60cddaec), `-1` calls 0x60ccf908 (and 0x60cdda80). Guards of the ISO-direct branch
(0x60cdc931..0x60cdc9c6, function 6): `(188,a2) != 0x5101`, rule 75 (`0x60cce3dc(75) == 1`) and `0x60cd20e9 == 1`, no card write (`0x60ccf2b6 == 0`); with
rule 75 failing or a card write in progress nothing is called at all. Also the screen state d2 must be in {9,10,11,12,13,26,15,20,21}.

## NOT proven (needs the camera)

* The meaning of `0x602ea74c` on the body: the design reads "returns 0 = no contact lens". It is called from 18 places; only the emulator stub, not the real
  function with a lens or without, has been run. If it means something else (or is 0 with a contact lens), ISO would replace FNo. in the wrong case.
* The physical sense of the counter (+1 = clockwise?) and whether ISO goes up or down for it; the generic (guard-failed) path is reversed with respect to
  the ISO-direct one, as above.
* That the overlay / screen shown while turning is the same as with the ISO button (the transition `REQ_ISO_DIRECT_MAIN` / `SUB_DIAL` comes from stock,
  but the screen stack is not emulated).
* Bulb / time modes (shutter value B / T in M): not covered; stock rules may refuse differently.
* Which mode value is 6 on the camera: from the study (sid 109, else sid 24 = 6 for M, as in dial_expcomp's rule engine note); the emulator uses the same numbers.
* The effect of the real getter 0x60ccf9f3 (the emulator stubs it per sid); the real stack depth below 0x602ea74c (above).

## Compatibility

The claim 0x60210900..0x6021093c is where full Caduceus keeps its 8-slot bundle table (CODE_SPACE_MAP): **do not combine with full Caduceus builds**
(sd_bundles, bundles, wb, v0.2 H/L). This repository's stock-based modules do not use that range. Pairing with `dial_expcomp` (M/B list entry 2 -> Exp comp)
is fine: that patch only changes data; dial_iso acts only when the free dial is on FNo. Flash one feature group at a time (FIRMWARE_GUIDE section 10).
