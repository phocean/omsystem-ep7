# Profile JPEG quality: first slot (LSF) instead of the second (LF) (E-P7 1.1)

In stock, when a profile rule fires (COLOR, MONO, art filters, a few other states) and the quality is "RAW only", the settings
dependency engine rewrites it to JPEG slot 2 + RAW, shown "LF + RAW" on this camera. With `jpeg_always` the RAW file is then not written,
so the profile shot is an LF JPEG. This patch makes the engine pick the first quality slot (LSF on this camera) instead.

## What changes (1 byte; `patches/profile_lsf/edits.json`)

| Address | Stock | Patched | Meaning |
|---|---|---|---|
| 0x6043c24e | 0f | 0e | results list 0x6043c24c of the sid 10 (quality) dependency rules: pair {0 -> 15} becomes {0 -> 14} |

External quality values (validator 0x604ccb6c): 10..13 = JPEG slot (selector 2, 1, 5, 0), 14..17 = the same + RAW, 0 = RAW only.
15 = (selector 1, RAW) is the second slot; 14 = (selector 2, RAW) is the first slot. The GUI table (0x61163d46) maps 10 and 14 to quality
slot 234 (the first of four) and 11 and 15 to slot 235 (the second). The 30 rules of the entry 0x6045e64c share the one results list, so all
states where stock forces "slot 2 + RAW" now force "slot 1 + RAW". Everything else (the other qualities, other slots) is stock.

## Checks and what is NOT proven

`patches/profile_lsf/verify.py` (static, run by `make final`): stock byte, only this byte differs, the list is the 9 pairs, the 30 rules are
its only references, 14 is a valid value (selector 2, flag 1), the slot mapping above.

Not proven: the label displayed ("LSF + RAW" expected), the EXIF, the shot counter, that the stored quality is restored when leaving the
profile (the engine has a restore path when no rule fires, 0x602b2dda..0x602b2e87, seen in static reading only, not confirmed on the camera), that the first slot is the LSF one on the camera (the user's list is LSF, LF, LN, MN in menu order, which matches
the mapping), and no emulator run of the engine 0x602b2961. Going back: set 0x0f again, or flash the previous firmware: value 14 is a stock value.
