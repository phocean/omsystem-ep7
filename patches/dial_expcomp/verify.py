#!/usr/bin/env python3
"""Static check of the E-P7 1.1 `dial_expcomp` patch (patches/dial_expcomp/edits.json). Offline, no emulator.

What it changes (4 edits): in Custom Menu B > "Dial function M/B" the two choices become {Shutter, Exposure comp} (function numbers 4 and 2, the
stock first choice {FNo., Shutter} is replaced) and {Shutter, FNo.} (stock second choice, untouched); the labels follow; and the rule engine no longer
disables exposure compensation in mode M.

Checks (exit 0 = all PASS):
  * every edit has the stock bytes as `expect`; nothing else of the 0x100 payload differs;
  * validator record 0x604ccd74 (sid 76) is untouched: list 0x604bb43c, alt 0x604ade7c, 2 entries of 64 bytes;
  * after the patch the first 64-byte entry of the M/B list is byte for byte the second entry of the shutter-priority
    record 0x604ccd60 (list 0x604bb3bc), i.e. an entry that stock already ships and that stock menus accept;
  * the second entry {Shutter, FNo.} is the stock one, unchanged;
  * the label lists of the M/B page after the patch: first dial Shutter / Shutter, second dial Exposure-comp icon (658) / FNo. (659), with the label id 658
    the one the A page uses for that function.
It does NOT prove that the camera accepts function 2 in mode M (rule 69 evaluated by the dial routine 0x60cdc82c):
that needs the camera (see docs/DIAL_EXPCOMP.md).
"""
import json, struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = 0x60020020
STOCK = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'analysis/ep7_1100/00_0100_406a0020.decoded.bin'
spec = json.loads((ROOT / 'patches/dial_expcomp/edits.json').read_text())
stock = STOCK.read_bytes()
img = bytearray(stock)
ok = True


def rep(name, good, detail=''):
    global ok
    ok &= bool(good)
    print(('PASS ' if good else 'FAIL ') + name + (f'  {detail}' if detail else ''))


for e in spec['edits']:
    a = int(e['addr'], 16) - BASE
    n = bytes.fromhex(e['new'])
    rep(f'stock bytes at {e["addr"]}', stock[a:a + len(n)].hex() == e['expect'], e['expect'])
    img[a:a + len(n)] = n
diff = [BASE + i for i in range(len(stock)) if stock[i] != img[i]]
rep('patch differs from stock only inside the 4 edit ranges', all(any(int(e['addr'], 16) <= a < int(e['addr'], 16) + len(e['new']) // 2 for e in spec['edits']) for a in diff), str([hex(x) for x in diff]))
rep('exactly 5 bytes change: 0x604bb43c (03->04), 0x604bb440 (04->02), label ids 0x611d6d32 and 0x611d6d4a, unlock 0x6044afda', diff == sorted([0x604bb43c, 0x604bb440, 0x611d6d32, 0x611d6d4a, 0x6044afda]) , str([hex(x) for x in diff]))


def u32(b, a): return struct.unpack_from('<I', b, a - BASE)[0]
def u16(b, a): return struct.unpack_from('<H', b, a - BASE)[0]
def raw(b, a, n): return bytes(b[a - BASE:a - BASE + n])


REC = {'P': 0x604ccd38, 'A': 0x604ccd4c, 'S': 0x604ccd60, 'M': 0x604ccd74}   # records of sids 70, 74, 72, 76 (shutter priority is the record 0x604ccd60)
m = REC['M']
rep('sid 76 record unchanged', raw(stock, m, 20) == raw(img, m, 20), raw(img, m, 20).hex())
lp, ap, size, es = u32(img, m + 4), u32(img, m + 8), u16(img, m + 12), u16(img, m + 14)
rep('M/B list 0x604bb43c, alt 0x604ade7c, 2 entries of 64 B', (lp, ap, size, es) == (0x604bb43c, 0x604ade7c, 128, 64), f'{lp:#x} {ap:#x} {size} {es}')
sl = u32(img, REC['S'] + 4)
rep('shutter-priority list at 0x604bb3bc', sl == 0x604bb3bc, hex(sl))
s_ents = [(u32(img, sl + 64 * k), u32(img, sl + 64 * k + 4)) for k in range(2)]
rep('stock shutter-priority entries are {2,4} and {4,2}', s_ents == [(2, 4), (4, 2)], str(s_ents))
rep('stock M/B entries are {3,4} and {4,3}', [(u32(stock, lp + 64 * k), u32(stock, lp + 64 * k + 4)) for k in range(2)] == [(3, 4), (4, 3)])
rep('M/B first entry now {4,2}', (u32(img, lp), u32(img, lp + 4)) == (4, 2))
rep('M/B first entry == shutter-priority second entry, byte for byte', raw(img, lp, 64) == raw(img, sl + 64, 64))
rep('M/B second entry {4,3} unchanged, byte for byte', raw(img, lp + 64, 64) == raw(stock, lp + 64, 64) and (u32(img, lp + 64), u32(img, lp + 68)) == (4, 3))

# label lists of the M/B page: 12-byte items {ptr, value, {kind u16, id u16}} (value 4 -> first entry, 8 -> second entry)
def item(b, a): return (u32(b, a + 4), u16(b, a + 8), u16(b, a + 10))
M0, M1 = 0x611d6d28, 0x611d6d40
want_stock = {M0: [(4, 4, 659), (8, 4, 660)], M1: [(4, 4, 660), (8, 4, 659)]}
want_new = {M0: [(4, 4, 660), (8, 4, 660)], M1: [(4, 4, 658), (8, 4, 659)]}
rep('stock M/B label lists = FNo./Shutter and Shutter/FNo.', {k: [item(stock, k + 12 * i) for i in range(2)] for k in want_stock} == want_stock)
rep('patched M/B label lists: first choice Shutter / ExpComp icon, second choice Shutter / FNo.', {k: [item(img, k + 12 * i) for i in range(2)] for k in want_new} == want_new)
# the same label id 658 is what the A page draws for exposure comp in its lists (0x611d6c58 / 0x611d6c7c)
a_items = [item(stock, a) for a in (0x611d6c58, 0x611d6c64, 0x611d6c70, 0x611d6c7c)]
rep('A page labels: (12 -> 658, 5 -> 659, 12 -> 659, 5 -> 658)', [(v, k, i) for v, k, i in a_items] == [(12, 4, 658), (5, 4, 659), (12, 4, 659), (5, 4, 658)], str(a_items))

# ---- third edit: rule engine group 0 for mode M no longer applies (sid 15210 compared with 2 instead of 0)
CND = 0x6044afd0
cnd = lambda b: [(u16(b, CND + 8 * i), u16(b, CND + 8 * i + 2)) for i in range(3)]
rep('stock group-0 conditions: {sid 24 == 6}, {sid 15210 == 0}, {sid 24 == 9}', cnd(stock) == [(24, 6), (15210, 0), (24, 9)], str(cnd(stock)))
rep('patched: {sid 24 == 6}, {sid 15210 == 2}', cnd(img)[:2] == [(24, 6), (15210, 2)], str(cnd(img)))
pat = struct.pack('<I', CND); refs, i = [], 0
while True:
    i = stock.find(pat, i)
    if i < 0:
        break
    refs.append(BASE + i)
    i += 1
rep('the condition block 0x6044afd0 has one abs32 reference (group 0 of the sid 2 entry 0x6045efac)', refs == [0x6044b518] and u32(stock, 0x6045efac + 4) == 0x6044b518, str([hex(x) for x in refs]))
print('ALL PASS' if ok else 'SOME FAILED')
sys.exit(0 if ok else 1)
