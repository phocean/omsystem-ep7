#!/usr/bin/env python3
"""Static check of the E-P7 1.1 `profile_lsf` patch (patches/profile_lsf/edits.json: 0x6043c24e  0f -> 0e). Offline.

In stock, the settings dependency engine rewrites the quality value "RAW only" (external value 0) to 15 when a profile
rule fires (COLOR / MONO / art filters / ...): 15 = {selector 1, RAW in addition}, displayed "<slot 2 quality> + RAW" (LF + RAW on this camera).
The patch changes the target to 14 = {selector 2, RAW in addition}, the same kind of value on the FIRST JPEG slot of the quality list.
The jpeg_always stub still removes the RAW file at capture.

Checks (exit 0 = all PASS): stock byte and the only differing byte; the results list is the 9 pairs {0->15, 10->10 ... 17->17}
and becomes {0->14, 10->10 ... 17->17}; all 30 rules of the sid 10 dependency entry (0x6045e64c, rules 0x6043c270) point to this
list and nothing else references it; 14 is a valid external value of the sid 10 validator (0x604ccb6c, list 0x604b3b3c, alt 0x604ad6ec) with
(selector, flag) = (2, 1); the GUI table (0x61163d46) maps 14 to the same quality slot as 10 (slot 234, the first of four) and 15 to slot 235 (the second);
the jpeg_always stub treats selector 2 as a JPEG selector (it only skips 3 and 4).
Not proven here (needs the camera): the label shown, the EXIF, the shot counter, that the stored value is restored when leaving the profile.
"""
import json, struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = 0x60020020
stock = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / 'analysis/ep7_1100/00_0100_406a0020.decoded.bin').read_bytes()
spec = json.loads((ROOT / 'patches/profile_lsf/edits.json').read_text())
img = bytearray(stock)
ok = True


def rep(name, good, detail=''):
    global ok
    ok &= bool(good)
    print(('PASS ' if good else 'FAIL ') + name + (f'  {detail}' if detail else ''))


for e in spec['edits']:
    a = int(e['addr'], 16) - BASE
    n = bytes.fromhex(e['new'])
    rep(f'stock byte at {e["addr"]}', stock[a:a + len(n)].hex() == e['expect'], e['expect'])
    img[a:a + len(n)] = n
diff = [BASE + i for i in range(len(stock)) if stock[i] != img[i]]
rep('only 0x6043c24e differs from stock', diff == [0x6043c24e], str([hex(x) for x in diff]))


def u16(b, a): return struct.unpack_from('<H', b, a - BASE)[0]
def u32(b, a): return struct.unpack_from('<I', b, a - BASE)[0]


RES = 0x6043c24c
pairs = lambda b: [(u16(b, RES + 4 * i), u16(b, RES + 4 * i + 2)) for i in range(9)]
want_stock = [(0, 15)] + [(v, v) for v in range(10, 18)]
want_new = [(0, 14)] + [(v, v) for v in range(10, 18)]
rep('stock results list = {0->15, 10..17 identity}', pairs(stock) == want_stock, str(pairs(stock)))
rep('patched results list = {0->14, 10..17 identity}', pairs(img) == want_new, str(pairs(img)))
ent = 0x6045e64c
rep('dependency entry of sid 10: key 0x0c80000a, 30 rules at 0x6043c270', (u32(stock, ent), u32(stock, ent + 4), u32(stock, ent + 8)) == (0x0c80000a, 0x6043c270, 30))
rules = [[u32(stock, 0x6043c270 + 16 * i + 4 * j) for j in range(4)] for i in range(30)]
rep('all 30 rules point to the results list (field +8) with 9 pairs (field +12)', all(r[2] == RES and r[3] == 9 for r in rules))
pat = struct.pack('<I', RES)
refs, i = [], 0
while True:
    i = stock.find(pat, i)
    if i < 0:
        break
    refs.append(BASE + i)
    i += 1
rep('the 30 rules are the only abs32 references to the results list', sorted(refs) == sorted(0x6043c270 + 16 * k + 8 for k in range(30)), f'{len(refs)} refs')
V, ALT = 0x604b3b3c, 0x604ad6ec
vl = [(u32(img, V + 64 * k), u32(img, V + 64 * k + 4)) for k in range(9)]
alt = [u32(img, ALT + 4 * k) for k in range(9)]
ext = dict(zip(alt, vl))
rep('external value 14 is valid and = (selector 2, RAW flag 1); 10 = (2, 0); 15 = (1, 1)', ext.get(14) == (2, 1) and ext.get(10) == (2, 0) and ext.get(15) == (1, 1), str(ext))
G = 0x61163d46
gui = {u16(img, G + 4 * k): u16(img, G + 4 * k + 2) for k in range(8)}
rep('GUI table: 10 and 14 -> slot 234; 11 and 15 -> slot 235', (gui[10], gui[14], gui[11], gui[15]) == (234, 234, 235, 235), str(gui))
rep('slot order: 10, 11, 12, 13 -> 234, 235, 236, 237 (first to fourth)', [gui[k] for k in (10, 11, 12, 13)] == [234, 235, 236, 237])
print('ALL PASS' if ok else 'SOME FAILED')
sys.exit(0 if ok else 1)
