# M/B dial: Shutter / Exposure comp and Shutter / FNo. (E-P7 1.1)

Custom Menu B > Dial function M/B offers two choices in stock: {FNo., Shutter} and the swapped {Shutter, FNo.}.
This patch replaces the first one: the two choices become **{Shutter, Exposure comp}** (first) and **{Shutter, FNo.}** (second, stock bytes), so
Shutter stays on the same dial in both and only the other dial changes. In mode M with ISO Auto, the exposure compensation moves the automatic
ISO, so that dial sets the ISO indirectly. The code module `dial_iso` (docs/DIAL_ISO.md) adds the lens logic: with a contact lens the
exposure-comp choice puts FNo. on the dial, without contacts the FNo. choice puts ISO on it.

## What changes (4 edits, 5 bytes change; `patches/dial_expcomp/edits.json`)

| Address | Stock | Patched | Meaning |
|---|---|---|---|
| 0x604bb43c (8 B) | `03000000 04000000` | `04000000 02000000` | first 64-byte entry of the M/B list (0x604bb43c): {FNo.(3), Shutter(4)} -> {Shutter(4), Exposure comp(2)}; the second entry {4,3} is untouched |
| 0x611d6d32 | `93 02` | `94 02` | label list of the first dial (0x611d6d28), GUI value 4 (first choice): label id 659 (FNo.) -> 660 (Shutter) |
| 0x611d6d4a | `94 02` | `92 02` | label list of the second dial (0x611d6d40), GUI value 4 (first choice): label id 660 (Shutter) -> 658 (@A008@, exposure comp icon) |
| 0x6044afda | 00 | 02 | rule engine (base 0x6045efac, sid 2 = exposure compensation), group 0 of mode M (sid 24 == 6): its second condition compares sid 15210 with 0; it now compares with 2, a value that 0/1 setting never has, so the group never applies |

Stored value: the setting of sid 76 is validated against the 64-byte entries of the list (record 0x604ccd74, alt table 0x604ade7c unchanged), i.e. it is
the function pair itself, {a, b}. A camera that had {4,2} stored (the previous build's second choice) now has the first choice; {4,3} stays the second
choice; a stored {3,4} (stock first choice) matches no entry any more: choose the wanted entry again in Custom Menu B after flashing (traced in the security review: an unmatched stored value is read as the last entry of the list, so the menu shows the second choice; the dial itself keeps working with {3,4}, the pair is just two valid functions).

Why the last edit: on the camera the dial on "Exp. comp." did nothing in mode M. The rule engine returns 256 ("disabled") for sid 2 in mode M when
sid 15210 is 0, so the dial rule 69 refuses and the event is ignored. Emulator run of the real engine 0x602af9d1 (stock vs patched, sid 2, mode M):
15210 = 0: 256 -> 0; 15210 = 1: 0 -> 0; modes P/A/S: 0 -> 0; movie flag set in M: 256 -> 0; bulb shutter value in M: 256 -> 0 (the bulb / time values are still
refused by canExecute(2)). Side effect: in M, exposure compensation becomes selectable like in P/A/S. A value left in A/S mode will then apply in M (check it is 0). With a fixed ISO it changes only the indicator.
The 19 conditions of canExecute(2) (record 0x60ae0838) were not evaluated to the end (sids 381, 323, 699, 278 are unknown); on the camera (previous build) the dial did change the exposure compensation.

After the patch the first entry of the M/B list is byte for byte the second entry of the shutter-priority record
(0x604bb3bc), so it is data that stock already ships. The validator record (0x604ccd74), its alt table and the sizes are unchanged.
The dial routine and the rules are untouched: function 2 follows the path the A and S modes already use for it.

## Checks and what is NOT proven

`patches/dial_expcomp/verify.py` (static, run by `make final`): stock bytes, only these bytes differ, record unchanged,
first entry identical to the shutter-priority one, second entry stock, label lists, and the label id 658 as the A page uses it.

Proven on the camera by the previous build (same function pair {4,2}, same unlock): the dial changes the exposure compensation in M.
Not proven (needs the camera): the menu screen with the new label lists (the first dial's list now says Shutter for both values), what the validator does with
a stored pair that is no longer in the list ({3,4}), and the effect with a fixed ISO (exposure compensation then changes only the exposure indicator).
Stock note: the user could not adjust exposure compensation in mode M with ISO Auto by any other control before this patch.
