#!/usr/bin/env python3
"""Emulator test of patches/jpeg_always (the REAL capture-record population function, the REAL getter 0x6005e971, the REAL stub
bytes; NO table, NO SD accessor, NO card state is mapped: any access to them would fault). Offline, read-only, no flash. docs/JPEG_ALWAYS.md.

  EP7_STOCK_MAIN=<decoded stock main> python3 -I patches/jpeg_always/emu_verify.py [--base release|stock] [--quick] [--jobs N] [--log FILE]
  --base release (default): v0.29a base image vs base + jpeg_always (needs releases/v0.29a/edits.json in this checkout)
  --base stock: the official STOCK main image vs stock + jpeg_always only (the --base stock build); no release is read
  --base final: the FINAL spec (generated/final/edits.json, --final-spec) minus its jpeg_always edits vs the whole FINAL spec (patches/final)
  (the engine, tools/ and analysis/ are read from the MAIN repository: $EP7_MAIN_REPO, default <this checkout>/../../.. )

What runs (MN103 instructions executed by the GNU libsim based engine of external/oly_fw_analysis, strict regions):
  F  the whole capture-record population function 0x602a7ea0..0x602a8874 (entered with the call the 5 callers use:
     `call 0x602a7ea0,[d2,d3,a2,a3],20`, d0 = slot id) on the base image and on base + jo edits. Regions: the whole
     image (rx, so any store into the image faults), the stack (rw), the capture record (rw, exactly 27332 B), the global
     source blob that 0x60300055 copies, the slot table read by 0x6029b9d1, the property registry (T2 table 0xa26ffa88,
     4096 entries -> 16 B value blocks) read by the REAL getter 0x6005e971 / 0x6005d924 / 0x6005efbd. Nothing else is
     mapped: any other access stops the run (memory_fault).
  S  the two capture sites alone (the 16-byte site sequence `mov key,d0; mov 0,a0; clr d1; call target,[d2,d3],12`) with the
     base getter vs jo_get, instruction trace -> stack depth, all 32 registers compared at the return address.
  M  mutation: bytes of the assembled stub are changed in the emulator image; the quick suite must FAIL for each mutant.
Exit code 0 = every check passes (and every mutant is killed).
"""
import argparse, itertools, json, os, random, struct, sys, time
from multiprocessing import get_context
from pathlib import Path

HERE = Path(__file__).resolve().parent
CK = HERE.parents[1]                                       # this checkout
MAIN_REPO = Path(os.environ.get('EP7_MAIN_REPO') or CK.parents[2])
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(MAIN_REPO / 'external/oly_fw_analysis/tools'))
import build as B                                          # noqa: E402
from penf_emulator import Region, execute, REGISTERS       # noqa: E402

BASE = B.BASE
AT = B.AT                                                  # jo_get 0x601de540
GETTER = B.GETTER
POP = 0x602a7ea0                                           # capture record population function
SITE1, SITE2 = 0x602a7f57, 0x602a7feb                      # the two redirected getter calls
RET1, RET2 = SITE1 + 7, SITE2 + 7
K_FLAG1, K_FLAG2, K_SEL1, K_SEL2 = B.K_FLAG1, B.K_FLAG2, B.K_SEL1, B.K_SEL2
K_PMODE, K_PMODE6, K_S2EN = B.K_PMODE, B.K_PMODE6, 0x52b1  # 0x52b1 = slot 2 enable (value 2 or 3 at 0x602a7f73)
OFF_T1, OFF_T2, OFF_SEL1, OFF_SEL2 = 23920, 23922, 24012, 24014
OFF_T1COPY = 23924                                         # 0x602a8012: +23924 = copy of +23920

# ---------------------------------------------------------------- synthetic RAM map (regions are exact)
CALLER, STACK, STACK_SZ, SP0 = 0x18000000, 0x18010000, 0x2000, 0x18011000
REC, REC_SZ = 0x62300000, 27332                            # 6833 words copied by 0x60300055
SLOTTBL = 0x6223d178                                       # 24 B entries (0x6029b9d1): +0 u16 flags (bit mask 4), +12 record ptr
BLOB = 0x6225882c
T2 = 0xa26ffa84                                            # u16 flag (0 -> only T2 used) then 4096 x (u32 ?, u32 ptr)
VAL = 0x62400000                                           # 4096 x 16 B value blocks (byte idx*size at +idx)


def rngbytes(seed, n):
    r = random.Random(seed)
    return bytes(r.randrange(256) for _ in range(n))


STATIC = {
    'caller_pop': b'\xdd' + struct.pack('<i', POP - CALLER) + b'\xf0\x14',
    'low': bytes(0x100),                                   # (0x8050) = core index 0 -> identity pointer translation 0x6005c8cc
    'blob': rngbytes(1, REC_SZ),
    'sz': bytes([7, 0, 9, 0]),
}
_slot = bytearray(26 * 24)
struct.pack_into('<H', _slot, 24, 0x04)
struct.pack_into('<I', _slot, 24 + 12, REC)
STATIC['slot'] = bytes(_slot)
_t2 = bytearray(4 + 8 * 4096)
for _i in range(4096):
    struct.pack_into('<I', _t2, 4 + _i * 8 + 4, VAL + _i * 16)
STATIC['t2'] = bytes(_t2)

IM = {}                          # name -> bytes, filled in main() before the pool forks


# ---------------------------------------------------------------- scenario
def scen(**kw):
    s = dict(mode=11, m6=0, sel1=0, sel2=0, raw1=1, raw2=1, s2en=2, noise=None)
    s.update(kw)
    return s


def eff_mode(s):
    return s['m6'] if s['mode'] == 6 else s['mode']


def overridden(s, slot):
    sel = s['sel1'] if slot == 1 else s['sel2']
    return eff_mode(s) in (11, 12) and sel not in (3, 4)


def ftype(sel, flag):
    return 2 if sel == 4 else 1 if sel == 3 else 5 if flag == 1 else 0


def model_types(s, patched):
    """(+23920, +23922) the capture record gets."""
    f1 = 0 if patched and overridden(s, 1) else s['raw1']
    f2 = 0 if patched and overridden(s, 2) else s['raw2']
    t1 = ftype(s['sel1'], f1)
    t2 = ftype(s['sel2'], f2) if s['s2en'] in (2, 3) else 0
    return t1, t2


def props(s):
    v = bytearray(rngbytes(s['noise'], 0x10000)) if s['noise'] is not None else bytearray(0x10000)

    def sp(key, val, idx=0):
        v[(key >> 4) * 16 + idx] = val
    sp(K_PMODE, s['mode']); sp(K_PMODE6, s['m6']); sp(K_SEL1, s['sel1']); sp(K_SEL2, s['sel2'])
    sp(K_FLAG1, s['raw1']); sp(K_FLAG2, s['raw2'])
    sp(K_FLAG1, 1 - s['raw1'], 1); sp(K_FLAG2, 1 - s['raw2'], 1)             # idx 1 differs from idx 0 (the sites only read idx 0)
    sp(K_S2EN, s['s2en'])
    return bytes(v)


def world(s, img):
    """Regions common to the function run and the site run."""
    return [Region('img', BASE, img, 'rx'), Region('low', 0x8000, STATIC['low'], 'r'),
            Region('t2', T2, STATIC['t2'], 'r'), Region('val', VAL, props(s), 'r')]


def paint():
    return rngbytes(7, STACK_SZ)


def image_for(name, s):
    """Images: 'base' / 'jo' (built once)."""
    return IM[name]


SENT = {'d2': 0x22222222, 'd3': 0x33333333, 'a2': 0x66666666, 'a3': 0x77777777, 'a1': 0x55555555, 'mdr': 0xa5a5a5a5, 'psw': 0}


def run_pop(imgname, s, bps=(), trace=0):
    img = image_for(imgname, s)
    rg = world(s, img) + [Region('caller', CALLER, STATIC['caller_pop'] + b'\xcb', 'rx'),
                          Region('stack', STACK, paint(), 'rw', True),
                          Region('slot', SLOTTBL, STATIC['slot'], 'r'), Region('blob', BLOB, STATIC['blob'], 'r'),
                          Region('sz', 0x622a0648, STATIC['sz'], 'r'), Region('rec', REC, bytes(REC_SZ), 'rw', True)]
    regs = dict(SENT, pc=CALLER, sp=SP0, d0=1, d1=0x11111111, a0=0x44444444)
    r = execute(rg, regs, CALLER + 7, limit=300000, trace_limit=trace, breakpoints=bps)
    mem = {m['name']: bytes.fromhex(m['hex']) for m in r['memory']}
    return r, mem


def run_site(imgname, s, key, target, idx=0):
    """The 16-byte site sequence (same encodings as 0x602a7f4e..0x602a7f5b) calling target."""
    img = image_for(imgname, s)
    ld = b'\xfc\xcc' + struct.pack('<I', key)               # mov imm32,d0 (the real sites use mov imm16 / imm32; same d0)
    d1 = b'\x04' if idx == 0 else b'\x85' + bytes([idx])
    pre = ld + b'\x90\x00' + d1
    callat = CALLER + len(pre)
    code = pre + b'\xdd' + struct.pack('<i', target - callat) + b'\xc0\x0c' + b'\xcb'
    rg = world(s, img) + [Region('caller', CALLER, code, 'rx'), Region('stack', STACK, paint(), 'rw', True)]
    regs = dict(SENT, pc=CALLER, sp=SP0, d0=0xdeadbeef, d1=0x99999999, a0=0x88888888)
    r = execute(rg, regs, callat + 7, limit=20000, trace_limit=5000)
    mem = {m['name']: bytes.fromhex(m['hex']) for m in r['memory']}
    return r, mem, callat


def regdiff(a, b, ignore=()):
    return {k: (hex(a[k]), hex(b[k])) for k in REGISTERS if a[k] != b[k] and k not in ignore}


def lowest_written(stack, sp0):
    """Depth below SP0 of the deepest changed byte (painted stack), and whether anything above SP0 changed."""
    p = paint()
    low = next((i for i in range(len(p)) if p[i] != stack[i]), None)
    depth = None if low is None else sp0 - (STACK + low)
    # `call` stores the return address at (0,sp) of the caller's frame (4 B at SP0 belong to the call itself)
    return depth, stack[sp0 + 4 - STACK:] != p[sp0 + 4 - STACK:]


# ---------------------------------------------------------------- checks
def ok_run(r, name, fails):
    if r['status'] not in ('returned', 'breakpoint') or r['fault']:
        fails.append(f'{name}: status {r["status"]} fault {r["fault"]}')
        return False
    return True


def check_pop(s, tag):
    """F: whole population function, base vs jo."""
    fails, info = [], {}
    rb, mb = run_pop('base', s)
    rj, mj = run_pop('jo', s)
    if not (ok_run(rb, 'base', fails) & ok_run(rj, 'jo', fails)):
        return fails, info
    for name, r in (('base', rb), ('jo', rj)):
        if r['registers']['pc'] != CALLER + 7 or r['registers']['sp'] != SP0:
            fails.append(f'{name}: exit pc/sp {r["registers"]["pc"]:#x}/{r["registers"]["sp"]:#x}')
        if any(r['registers'][k] != SENT[k] for k in ('d2', 'd3', 'a2', 'a3')):
            fails.append(f'{name}: callee-saved registers not restored')
    rec_b, rec_j = mb['rec'], mj['rec']
    hw = lambda m, o: struct.unpack_from('<H', m, o)[0]
    exp_b, exp_j = model_types(s, False), model_types(s, True)
    if (hw(rec_b, OFF_T1), hw(rec_b, OFF_T2)) != exp_b:
        fails.append(f'base record +23920/+23922 = {(hw(rec_b, OFF_T1), hw(rec_b, OFF_T2))}, model {exp_b}')
    if (hw(rec_j, OFF_T1), hw(rec_j, OFF_T2)) != exp_j:
        fails.append(f'jo record +23920/+23922 = {(hw(rec_j, OFF_T1), hw(rec_j, OFF_T2))}, model {exp_j}')
    if hw(rec_j, OFF_T1COPY) != hw(rec_j, OFF_T1):
        fails.append('jo record +23924 != +23920')
    exp = bytearray(rec_b)
    struct.pack_into('<HH', exp, OFF_T1, *exp_j)
    struct.pack_into('<H', exp, OFF_T1COPY, exp_j[0])
    diff = [i for i in range(REC_SZ) if rec_b[i] != rec_j[i]]
    if bytes(exp) != rec_j:
        bad = [i for i in range(REC_SZ) if exp[i] != rec_j[i]]
        fails.append(f'jo record differs from base outside the expected halfwords at offsets {bad[:8]}')
    for sel_off, k in ((OFF_SEL1, 'sel1'), (OFF_SEL2, 'sel2')):
        if hw(rec_j, sel_off) != hw(rec_b, sel_off):
            fails.append(f'selector copy +{sel_off} changed')
    if regdiff(rb['registers'], rj['registers']):
        fails.append(f'exit registers differ: {regdiff(rb["registers"], rj["registers"])}')
    for name, m in (('base', mb), ('jo', mj)):
        if m['stack'][SP0 + 4 - STACK:] != paint()[SP0 + 4 - STACK:]:
            fails.append(f'{name}: stack above the entry SP modified')
    info['diff'] = diff
    info['types'] = (exp_b, exp_j)
    return fails, info


def check_site(s, key, idx, tag, expect_override=None):
    """S: one getter call, base getter vs jo_get. Returns fails, info(depth ...)."""
    fails, info = [], {}
    rb, mb, cb = run_site('base', s, key, GETTER, idx)
    rj, mj, cj = run_site('jo', s, key, AT, idx)
    if not (ok_run(rb, 'base', fails) & ok_run(rj, 'jo', fails)):
        return fails, info
    ov = expect_override
    d0b, d0j = rb['registers']['d0'], rj['registers']['d0']
    exp_d0 = 0 if ov else d0b
    if d0j != exp_d0:
        fails.append(f'd0 = {d0j:#x}, expected {exp_d0:#x} (base getter {d0b:#x}, override {ov})')
    dif = regdiff(rb['registers'], rj['registers'], ignore=('d0',))
    if dif:
        fails.append(f'registers differ from the stock getter call: {dif}')
    for name, m in (('base', mb), ('jo', mj)):
        d, above = lowest_written(m['stack'], SP0)
        info[name + '_depth'] = d
        if above:
            fails.append(f'{name}: stack above the site SP written')
    for name, r in (('base', rb), ('jo', rj)):
        sps = [t['sp'] for t in r['trace']] + [r['registers']['sp']]
        if any(x % 4 for x in sps):
            fails.append(f'{name}: SP not 4-aligned during the call')
        info[name + '_minsp'] = SP0 - min(sps)
        info[name + '_n'] = r['completed']
    info['ov'] = bool(ov)
    return fails, info


# ---------------------------------------------------------------- scenario sets
def matrix_main():
    out = []
    for (mode, m6), sel, raw in itertools.product(
            [(5, 0), (6, 5), (6, 11), (6, 12), (6, 0), (10, 0), (11, 0), (12, 0), (13, 0), (0, 0), (255, 0)], range(6), (0, 1)):
        out.append(scen(mode=mode, m6=m6, sel1=sel, sel2=sel, raw1=raw, raw2=raw))
    return out


def matrix_cross():
    out = [scen(sel1=a, sel2=b) for a in range(6) for b in range(6)]
    out += [scen(raw1=a, raw2=b) for a in (0, 1) for b in (0, 1)]
    out += [scen(raw1=a, raw2=b, sel1=3, sel2=1) for a in (0, 1) for b in (0, 1)]
    out += [scen(raw1=a, raw2=b, sel1=1, sel2=4) for a in (0, 1) for b in (0, 1)]
    out += [scen(s2en=e) for e in (0, 1, 2, 3, 4)]
    return out


def matrix_noise():
    return [scen(noise=n, mode=m, sel1=sel, sel2=(sel + 1) % 6, raw1=n & 1, raw2=(n >> 1) & 1)
            for n, (m, sel) in enumerate(itertools.product((5, 6, 11, 12), (0, 1, 2, 3, 4, 5)), 1)]


FOREIGN = [(0x8141, 0), (0x9481, 0), (0x1234, 0), (0x8230, 0), (0x8232, 0), (0x5140, 0), (0x5142, 0), (0x8231 ^ 0x100, 0),
           (0xffff, 0), (0x0001, 0), (K_FLAG1, 1), (K_FLAG2, 1), (0x18231, 0), (0x15141, 1), (0x8131, 0), (0x5231, 0)]


def task(t):
    kind, s, key, idx, extra = t
    try:
        if kind == 'pop':
            f, i = check_pop(s, None)
        else:
            f, i = check_site(s, key, idx, None, extra)
    except Exception as e:                                # an engine error counts as a failure, not a crash
        f, i = [f'exception {type(e).__name__}: {e}'], {}
    return t, f, i


def foreign_tasks():
    out = []
    for k, i in FOREIGN:
        for m in (11, 12, 5, 6, 13):
            slot = 1 if (k & 0xffff) == K_FLAG1 else 2 if (k & 0xffff) == K_FLAG2 else 0
            sc = scen(mode=m)
            out.append(('site', sc, k, i, bool(slot) and overridden(sc, slot)))
    return out


def site_tasks(scs):
    out = []
    for s in scs:
        out.append(('site', s, K_FLAG1, 0, overridden(s, 1)))
        out.append(('site', s, K_FLAG2, 0, overridden(s, 2)))
    return out


def describe(s):
    d = {k: v for k, v in s.items() if v != scen()[k]}
    return json.dumps(d, sort_keys=True)


def run_tasks(tasks, jobs, label):
    ctx = get_context('fork')
    res = []
    t0 = time.time()
    with ctx.Pool(jobs) as p:
        for x in p.imap_unordered(task, tasks, chunksize=2):
            res.append(x)
    bad = [x for x in res if x[1]]
    print(f'  {label}: {len(res) - len(bad)}/{len(res)} PASS ({time.time() - t0:.0f} s)')
    return res, bad


# ---------------------------------------------------------------- images
def build_images(which, final_spec=None):
    stock = B.STOCK.read_bytes()
    if which == 'final':      # patches/final: base = the FINAL spec minus the jpeg_always edits, jo = the FINAL spec itself
        fin = json.loads(Path(final_spec).read_text())
        base = dict(fin, edits=[e for e in fin['edits'] if e.get('source') != 'patches/jpeg_always'])
        spec, _ = B.apply({'components': ['0x100', '0x101'], 'edits': []}, '', False, False, True)     # metadata of the stub only
        IM['base'], IM['jo'] = B.img_of(base, stock), B.img_of(fin, stock)
        if [x for x in fin['edits'] if x.get('source') == 'patches/jpeg_always'] != spec['edits']:
            raise SystemExit('the jpeg_always edits of the final spec differ from a fresh --base stock build')
        return spec
    if which == 'stock':
        base = {'components': ['0x100', '0x101'], 'edits': []}
        spec, _ = B.apply(base, '', False, False, True)
    else:
        base = json.loads((CK / 'releases/v0.29a/edits.json').read_text())
        spec, _ = B.apply(base)
    IM['base'], IM['jo'] = B.img_of(base, stock), B.img_of(spec, stock)
    return spec


def mutated(k, edits):
    v = bytearray(IM['jo'])
    for a, old, new in edits:
        if v[a - BASE] != old:
            raise SystemExit(f'mutant byte {a:#x} is {v[a - BASE]:#04x}, expected {old:#04x}')
        v[a - BASE] = new
    IM['jo'] = bytes(v)


MUTANTS = {                       # CPU address, original byte, mutated byte (offsets from build.py's stub, jo_get 0x601de540)
    'selector 3 test: cmp 3 -> cmp 5': [(0x601de563, 0x03, 0x05)],
    'selector 3 test: beq -> bne': [(0x601de564, 0xc8, 0xc9)],
    'selector 4 test: cmp 4 -> cmp 5': [(0x601de567, 0x04, 0x05)],
    'mode 11 test -> 10': [(0x601de58b, 0x0b, 0x0a)],
    'mode 11 test: beq -> bne': [(0x601de58c, 0xc8, 0xc9)],
    'mode 12 test -> 13': [(0x601de58f, 0x0c, 0x0d)],
    'mode-6 re-resolve test: bne -> beq': [(0x601de57a, 0xc9, 0xc8)],
    'mode key 0x9481 -> 0x9581 (other property id)': [(0x601de56c, 0x94, 0x95)],
    'selector read: clr d1 -> inc d1': [(0x601de558, 0x04, 0x44)],
    'override value: clr d2 -> inc d2': [(0x601de5a1, 0x08, 0x48)],
    'override frame 12 -> 8': [(0x601de5ac, 0x0c, 0x08)],
    'override: idx not restored (mov d3,d1 -> exthu d0)': [(0x601de59e, 0x8d, 0x1c)],
    'pass: d1 not restored (mov d3,d1 -> exthu d0)': [(0x601de594, 0x8d, 0x1c)],
    'pass: mov 0,a0 -> mov 1,a0': [(0x601de596, 0x00, 0x01)],
    'slot-2 key 0x5141 compare 0x5141 -> 0x5142 and mode 11 -> 10': [(0x601de54b, 0x41, 0x42), (0x601de58b, 0x0b, 0x0a)],
    '3 bytes: selector 3 and 4 tests -> 5, mode 12 -> 13': [(0x601de563, 0x03, 0x05), (0x601de567, 0x04, 0x05), (0x601de58f, 0x0c, 0x0d)],
}


def quick_tasks():
    """A short suite hitting every decision of the stub (used for the mutation run; the full suite is a superset)."""
    scs = []
    for (mode, m6) in [(5, 0), (6, 11), (6, 12), (6, 5), (10, 0), (11, 0), (12, 0), (13, 0)]:
        for sel in range(6):
            scs.append(scen(mode=mode, m6=m6, sel1=sel, sel2=sel))
    scs += [scen(sel1=a, sel2=b) for a, b in ((3, 1), (1, 3), (4, 0), (0, 4), (2, 5))]
    tasks = site_tasks(scs)
    tasks += foreign_tasks()
    tasks += [('pop', scen(mode=m, sel1=a, sel2=b), None, 0, None) for m in (5, 11, 12) for a, b in ((0, 0), (3, 0), (0, 4))]
    return tasks


def mutation_test(jobs):
    print('M  mutation: stub bytes changed in the emulator image; the quick suite must fail')
    killed = 0
    saved = {k: v for k, v in IM.items()}
    rows = []
    for name, edits in MUTANTS.items():
        IM.clear(); IM.update(saved)
        try:
            mutated(name, edits)
        except SystemExit as e:
            print('   ', e); return False
        ctx = get_context('fork')
        why = None
        with ctx.Pool(jobs) as p:
            for t, f, i in p.imap_unordered(task, quick_tasks(), chunksize=2):
                if f:
                    why = (t, f[0]); p.terminate(); break
        dead = why is not None
        killed += dead
        print(f'   {"KILLED  " if dead else "SURVIVED"} {name}' + (f'   <- {describe(why[0][1]) if why[0][0] == "pop" else describe(why[0][1])}'
                                                                     f' key {why[0][2] and hex(why[0][2])}: {why[1][:110]}' if dead else ''))
    IM.clear(); IM.update(saved)
    print(f'   {killed}/{len(MUTANTS)} mutants killed')
    return killed == len(MUTANTS)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--quick', action='store_true', help='skip the big matrices (still runs the named cases and the mutation test)')
    ap.add_argument('--jobs', type=int, default=8)
    ap.add_argument('--log', type=Path, help='write one line per case here')
    ap.add_argument('--no-mutation', action='store_true')
    ap.add_argument('--base', default='release', choices=('release', 'stock', 'final'))
    ap.add_argument('--final-spec', type=Path, default=CK / 'generated/final/edits.json', help='--base final: the final edits.json')
    a = ap.parse_args()
    spec = build_images(a.base, a.final_spec)
    meta = spec['jpeg_always']
    nd = sum(x != y for x, y in zip(IM['base'], IM['jo']))
    print(f"image: {'STOCK main' if a.base == 'stock' else 'FINAL spec without jpeg_always' if a.base == 'final' else 'v0.29a base'} + jo, {nd} bytes differ ({meta['code_len']} B at {meta['code_at']}, sites {meta['sites']}); engine {MAIN_REPO}")
    log, allbad = [], []
    sections = [('F/S matrix main (11 modes x 6 selectors x raw 0/1; no option exists)', matrix_main(), True),
                ('F/S selector pairs, mixed RAW flags, slot-2 enable', matrix_cross(), True),
                ('F/S random property noise (all other properties random)', matrix_noise(), True)]
    if a.quick:
        sections = [(n, m[:60], f) for n, m, f in sections]
    depth = {}
    print('F/S results')
    for label, scs, _ in sections:
        tasks = [('pop', s, None, 0, None) for s in scs] + site_tasks(scs)
        res, bad = run_tasks(tasks, a.jobs, label)
        allbad += bad
        for t, f, i in res:
            kind, s = t[0], t[1]
            key = hex(t[2]) if t[2] else '-'
            log.append(f'{"FAIL" if f else "PASS"} {kind} {key} {describe(s)} {i if not f else f}')
            if kind == 'site' and not f and i:
                cls = 'override' if i['ov'] else 'stock-path'
                d = depth.setdefault(cls, dict(jo=0, base=0, jomin=0, basemin=0, delta=-99))
                d['jo'] = max(d['jo'], i['jo_minsp']); d['base'] = max(d['base'], i['base_minsp'])
                d['jomin'] = max(d['jomin'], i['jo_depth'] or 0); d['basemin'] = max(d['basemin'], i['base_depth'] or 0)
                d['delta'] = max(d['delta'], i['jo_minsp'] - i['base_minsp'])
    # per-class summary lines of the explicit requirements
    print('named checks (each line = all matching cases of the matrices above)')
    cases = [(t, f) for t, f, i in [] ]
    # (1)-(5) are summarised from the log by predicate on the scenarios; recompute from the model, not from the engine
    summary = {}
    for s in [x for _, scs, _ in sections for x in scs]:
        for slot in (1, 2):
            if overridden(s, slot):
                c = '(2) mode 11/12 (or mode 6 resolved to 11/12), JPEG selector -> flag forced to 0, always'
            elif eff_mode(s) not in (11, 12):
                c = '(1) mode not in {11,12} -> identical to base'
            else:
                c = '(2) selector 3/4 -> identical to base'
            summary[c] = summary.get(c, 0) + 1
    for c, n in sorted(summary.items()):
        print(f'  {c}: {n} slot-cases modelled')
    # foreign keys
    ft = foreign_tasks()
    res, bad = run_tasks(ft, a.jobs, 'S foreign keys / idx / dirty key through jo_get (must equal the base getter exactly)')
    allbad += bad
    for t, f, i in res:
        log.append(f'{"FAIL" if f else "PASS"} foreign {hex(t[2])} idx {t[3]} {describe(t[1])} {f}')
    # register/contract at the REAL site return inside the REAL function (breakpoint), 3 scenarios
    print('B breakpoint at the real site return addresses inside the real function (all 32 registers, base vs jo)')
    for s, nm in ((scen(), 'override both slots'), (scen(mode=12), 'mode 12'), (scen(mode=6, m6=11), 'mode 6 -> 11'), (scen(mode=5), 'mode 5'),
                  (scen(sel1=3, sel2=4), 'selectors 3/4')):
        for bp, slot in ((RET1, 1), (RET2, 2)):
            rb, _ = run_pop('base', s, bps=(bp,))
            rj, _ = run_pop('jo', s, bps=(bp,))
            f = []
            if not (s['sel1' if slot == 1 else 'sel2'] not in (3, 4)):          # selector 3/4: the capture skips the getter call
                if rb['status'] != 'returned' or rj['status'] != 'returned' or regdiff(rb['registers'], rj['registers']):
                    f.append('selector 3/4: the site must not be reached, runs must end identically')
            elif rb['status'] != 'breakpoint' or rj['status'] != 'breakpoint':
                f.append(f'status {rb["status"]}/{rj["status"]} fault {rb["fault"]} {rj["fault"]}')
            else:
                ov = overridden(s, slot)
                dif = regdiff(rb['registers'], rj['registers'], ignore=('d0',))
                exp = 0 if ov else rb['registers']['d0']
                if dif:
                    f.append(f'registers {dif}')
                if rj['registers']['d0'] != exp:
                    f.append(f'd0 {rj["registers"]["d0"]:#x} expected {exp:#x}')
            line = f'{"FAIL" if f else "PASS"} slot {slot} {nm}: ' + (str(f) if f else
                   f'd0 base {rb["registers"]["d0"]} jo {rj["registers"]["d0"]}; sp/d1/d2/d3/a0/a1/a2/a3/mdr/psw identical')
            print('  ' + line)
            log.append(line)
            if f:
                allbad.append((('bp', s, None, 0, None), f, {}))
    print('D stack depth of the stub (instruction traces of the site call, SP0 = site SP)')
    for cls in ('stock-path', 'override'):
        d = depth.get(cls)
        if d:
            print(f'  {cls}: base getter call max {d["base"]} B below SP0, jo_get call max {d["jo"]} B, extra (max over cases) {d["delta"]} B; '
                  f'painted-stack high-water base {d["basemin"]} B / jo {d["jomin"]} B')
    if a.log:
        a.log.write_text('\n'.join(log) + '\n')
    ok = not allbad
    for t, f, i in allbad[:20]:
        print('FAIL', t[0], describe(t[1]), hex(t[2]) if t[2] else '', f)
    print(f'bytes differing from the {"STOCK" if a.base == "stock" else "final-without-jpeg_always" if a.base == "final" else "v0.29a base"} image in the emulated image: {nd}')
    ok_mut = True
    if not a.no_mutation:
        ok_mut = mutation_test(a.jobs)
    print('RESULT', 'PASS' if ok and ok_mut else 'FAIL', f'({len(log)} cases, {len(allbad)} failing)')
    sys.exit(0 if ok and ok_mut else 1)


if __name__ == '__main__':
    main()
