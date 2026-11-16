# M/B dial: Shutter / Exposure comp (E-P7 1.1)

Custom Menu B > Dial function M/B offers two choices in stock: {FNo., Shutter} and the swapped {Shutter, FNo.}.
This patch turns the second choice into {Shutter, Exposure comp}. In mode M with ISO Auto, the exposure
compensation moves the automatic ISO, so the free dial sets the ISO indirectly. With a lens that has electronic contacts, pick
the first choice to keep FNo. on the dial.

## What changes (2 edits, 3 bytes; `patches/dial_expcomp/edits.json`)

| Address | Stock | Patched | Meaning |
|---|---|---|---|
| 0x604bb480 | 03 | 02 | second word of the second 64-byte entry of the M/B list (0x604bb43c): function 3 (FNo.) -> 2 (exposure comp) |
| 0x611d6d56 | 93 02 | 92 02 | label id of that choice for the second dial: 659 (FNo.) -> 658 (exposure comp icon) |

After the patch the second entry of the M/B list is byte for byte the second entry of the shutter-priority record
(0x604bb3bc), so it is data that stock already ships. The validator record (0x604ccd74), its alt table and the sizes are unchanged.
The dial routine and the rules are untouched: function 2 follows the path the A and S modes already use for it.

## Checks and what is NOT proven

`patches/dial_expcomp/verify.py` (static, run by `make final`): stock bytes, only these bytes differ, record unchanged,
entry identical to the shutter-priority one, label lists, and the label id 658 as the A page uses it.

Not proven (needs the camera): that the dial routine accepts function 2 in mode M (rule 69 and the unnamed setting 15210 were not
evaluated to the end), that the menu writes the value 2 for the second dial, what the screen shows, and the effect with a fixed ISO
(exposure compensation then changes only the exposure indicator).
Stock note: the user could not adjust exposure compensation in mode M with ISO Auto by any other control before this patch.
