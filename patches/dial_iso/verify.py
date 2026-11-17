#!/usr/bin/env python3
"""Verifier of the E-P7 1.1 `dial_iso` patch (patches/dial_iso/edits.json). Offline, read-only, no flash. docs/DIAL_ISO.md.

  EP7_MAIN_REPO=<checkout holding external/oly_fw_analysis> PYTHONPATH=<it>/external/oly_fw_analysis/tools \\
  python3 -I patches/dial_iso/verify.py [edits.json] [--decoded PATCHED_DECODED_MAIN]     exit 0 = everything PASS, every mutant DETECTED

P  package: stock + edits == the patched image; only the bytes of the two edits differ (stub 0x60210900..0x6021094c, hook 0x60cdc837..0x60cdc840);
   `expect` bytes are stock; edits.json is exactly what build.py produces now; with --decoded, that decoded main (e.g. out/*/ payload) equals
   stock + edits.json.
E  the REAL dial routine 0x60cdc82c (entered by the call its callers use: `call 0x60cdc82c,[d2,d3,a2,a3],56`, d0 = event, d1 = counter,
   a1 = ctx), the REAL rule 0x60cc8be9, the REAL ISO-direct helpers 0x60cdda80 / 0x60cddaec / 0x60cde346; every other callee is a stub placed
   at its own address with the frame read from its call site (settings getter 0x60ccf9f3 returns per-sid values, 0x602ea74c the lens flag).
   Image regions are read-only (a store into the image faults). Runs, each stock vs patched, same inputs:
   E1  512 cases = functions {2,3} x 2 events x counter +-1 x mode key {3,4,5,6} x lens {0,1} x d2 {9,12,13,19} x 0x60ceca1d {0,1}:
       function 3, key 6, lens 0 (target ISO): a3 = 6, rule called with 6, ISO-direct branch (d2 in 9/12/13): 0x60cde346(6, counter),
       (32,a2) = 215 / 216, (192,a2) = 0x5704;
       function 2, key 6, lens 1 (target FNo.): everything identical to the stock run with function 3;
       every other case: all of calls, return, (32,a2), (192,a2), (272/276,a2), sp, registers, stack above sp identical to the stock run with the same function.
   E2  oracle runs: patched(fn, inputs) == stock(fn' , inputs), fn' = 6 if (fn == 3 and key == 6 and lens == 0), 3 if (fn == 2 and key == 6 and lens != 0), else fn; key = sid 109 else sid 24;
       compared at the resume point 0x60cdc840 and at the end; 600 random combinations of every input (fn 2..9, sids, lens, guards of the ISO-direct
       branch: rule 75, 0x60cd20e9, card write, (188,a2) = 0x5101, d2 states, event, counter, 0x60ceca1d).
   E3  MDR: differs at the resume point (the stub's calls leave their own return address), identical at the end; the first MDR access after the
       resume point is a `call` (written, never read).
M  mutants of the stub / hook; the E1 + E2 quick suite must FAIL for each. Two mutations are deliberately NOT listed because they are
   equivalent: dropping the lens-branch `cmp 2,a3` test (the entry gate already lets only functions 2 and 3 through, and 3 -> 3), and dropping the
   entry gate `cmp 2,d0 ; bne` (functions other than 2 / 3 then fail both later tests and keep a3; the only difference is two extra reads of settings).
"""
import importlib.util, itertools, json, os, random, re, struct, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CK = HERE.parents[1]
MAIN_REPO = Path(os.environ.get('EP7_MAIN_REPO') or CK)
sys.path.insert(0, str(MAIN_REPO / 'external/oly_fw_analysis/tools'))
from penf_emulator import execute, Region  # noqa: E402


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


B = _load('dial_iso_build', HERE / 'build.py')
BASE, AT, END, HOOK, HOOK_END, RESUME = B.BASE, B.AT, B.END, B.HOOK, B.HOOK_END, B.RESUME
TC = B.TC
STOCK = B.STOCK.read_bytes()
FN, FN_END = 0x60cdc82c, 0x60cdcbde
ok = True


def rep(name, good, detail=''):
    global ok
    ok &= bool(good)
    print(('PASS ' if good else 'FAIL ') + name + (f'  {detail}' if detail else ''), flush=True)


# ------------------------------------------------------------------ package
def apply(img, spec):
    d = bytearray(img)
    for e in spec['edits']:
        a, exp, new = int(e['addr'], 16) - BASE, bytes.fromhex(e['expect']), bytes.fromhex(e['new'])
        if bytes(d[a:a + len(exp)]) != exp or len(exp) != len(new):
            raise SystemExit(f'edit {e["addr"]}: expect does not match / length differs')
        d[a:a + len(new)] = new
    return bytes(d)


def package(spec_path, decoded):
    spec = json.loads(spec_path.read_text())
    rep('P components = [0x100], 2 edits', spec['components'] == ['0x100'] and len(spec['edits']) == 2)
    rep('P every edit has stock `expect`', all(STOCK[int(e['addr'], 16) - BASE:int(e['addr'], 16) - BASE + len(e['expect']) // 2].hex() == e['expect'] for e in spec['edits']))
    img = apply(STOCK, spec)
    diff = [BASE + i for i in range(len(STOCK)) if STOCK[i] != img[i]]
    inside = all(AT <= a < END or HOOK <= a < HOOK_END for a in diff)
    rep('P only module bytes differ from stock', inside and diff and len(img) == len(STOCK), f'{len(diff)} bytes differ')
    code, jmp, *_ = B.build(STOCK)
    rep('P edits.json == what build.py produces now (stub + hook bytes)', [bytes.fromhex(e['new']) for e in spec['edits']] == [jmp, code])
    rep('P hook = `jmp 0x60210900` + 4 nop, resume 0x60cdc840 is a whole stock instruction',
        img[HOOK - BASE] == 0xdc and HOOK + struct.unpack_from('<i', img, HOOK + 1 - BASE)[0] == AT and img[HOOK + 5 - BASE:HOOK_END - BASE] == b'\xcb' * 4)
    ranges = {(int(e['addr'], 16), int(e['addr'], 16) + len(e['new']) // 2) for e in spec['edits']}
    rep('P ranges for tools/fork_build.py STOCK_MODULES', ranges == {(0x60210900, 0x6021094c), (0x60cdc837, 0x60cdc840)}, str([(hex(a), hex(b)) for a, b in sorted(ranges)]))
    if decoded:
        d = Path(decoded).read_bytes()
        rep('P --decoded main == stock + edits.json byte for byte', d == img, f'{len(d)} B')
    return img


# ------------------------------------------------------------------ assembler helper for stubs
_c = {}


def asm(text):
    if text not in _c:
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            (t / 's.s').write_text('.am33_2\n.text\n' + text + '\n')
            subprocess.run([TC / 'mn10300-elf-as', '-o', t / 's.o', t / 's.s'], check=True)
            subprocess.run([TC / 'mn10300-elf-ld', '-Ttext=0x1000', '-e', '0', '-o', t / 's.elf', t / 's.o'], check=True)
            subprocess.run([TC / 'mn10300-elf-objcopy', '-O', 'binary', '-j', '.text', t / 's.elf', t / 's.bin'], check=True)
            _c[text] = (t / 's.bin').read_bytes()
    return _c[text]


STACK, SP0, WRAP, CTX, OBJ, VT, METH = 0x18010000, 0x18010000 + 0x1800, 0x18020000, 0x1a000000, 0x1c000000, 0x1c000100, 0x1d000000
REAL = [(FN, FN_END), (0x60cc8be9, 0x60cc8c0b), (0x60cdda80, 0x60cddba8), (0x60cde346, 0x60cde373)]
REALDATA = [(0x60f38dd4, 0x60f38e00)]            # the rule table read by 0x60cc8be9
GATED = (0x60ccf908, 0x60ccf94a, 0x60cde346, 0x60cddaec, 0x60cdda80, 0x60cc8be9)
_CS = {}


def callsites():
    if not _CS:
        with tempfile.NamedTemporaryFile(suffix='.bin') as tf:
            tf.write(STOCK)
            tf.flush()
            for a, b in REAL:
                t = subprocess.run([TC / 'mn10300-elf-objdump', '-b', 'binary', '-m', 'am33-2', '-D', f'--adjust-vma={BASE:#x}',
                                    f'--start-address={a:#x}', f'--stop-address={b:#x}', tf.name], capture_output=True, text=True, check=True).stdout
                for m in re.finditer(r'\tcall\s+0x([0-9a-f]+),\[([a-z0-9,]*)\],(\d+)', t):
                    _CS.setdefault(int(m.group(1), 16), set()).add((m.group(2), int(m.group(3))))
        for k, v in _CS.items():
            assert len(v) == 1, (hex(k), v)
        for k in list(_CS):
            _CS[k] = next(iter(_CS[k]))
    return _CS


def retins(regs, n):
    return ' retf [],0' if (regs == '' and n == 0) else f' ret [{regs}],{n}'


def world(img, fn, ev, cnt, s109, s24, s26, lens, d2v, ceca, r75=1, r20e9=1, write=0, a188=0, s267=0):
    cs = callsites()
    ov = {0x60cc8b23: f' mov {fn},d0', 0x60cc9a05: f' mov {ev},d0', 0x60ceca1d: f' mov {ceca},d0', 0x60cce3dc: f' mov {r75},d0',
          0x60cd20e9: f' mov {r20e9},d0', 0x60ccf2b6: f' mov {write},d0', 0x60cd47f2: ' nop', 0x60cde688: ' mov 0,d0', 0x60cd5752: ' mov 0,d0'}
    ctx = bytearray(1024)
    struct.pack_into('<I', ctx, 188, a188)
    rg = [Region('stack', STACK, bytes(0x2000), 'rw', True), Region('ctx', CTX, bytes(ctx), 'rw', True)]
    for a, b in REAL:
        rg.append(Region('r%x' % a, a, img[a - BASE:b - BASE], 'rx'))
    for a, b in REALDATA:
        rg.append(Region('d%x' % a, a, img[a - BASE:b - BASE], 'r'))
    rg.append(Region('stubarea', AT, img[AT - BASE:AT - BASE + 0x80], 'rx'))
    sids = {109: s109, 24: s24, 26: s26, 267: s267}
    gl = [f' cmp {s},d0\n bne g{i}\n mov {v},d0\n ret [d2,a2],24\ng{i}:' for i, (s, v) in enumerate(sids.items())]
    rg.append(Region('getsid', B.GETSID, asm('\n'.join(gl) + '\n mov 0,d0\n ret [d2,a2],24'), 'rx'))
    ob = bytearray(0x2000)
    struct.pack_into('<I', ob, 0, VT)
    for off in range(0, 400, 4):
        struct.pack_into('<I', ob, 0x100 + off, METH)
    struct.pack_into('<I', ob, 0x100 + 120, METH + 16)          # method +120 of the object: the screen / state id d2
    rg.append(Region('obj', OBJ, bytes(ob), 'r'))
    rg.append(Region('meth', METH, asm(' mov 1,d0\n rets').ljust(16, b'\xcb') + asm(f' mov {d2v},d0\n rets'), 'rx'))
    rg.append(Region('lens', B.LENS, asm(f' mov {lens},d0\n ret [d2],28'), 'rx'))
    done = {B.GETSID, B.LENS}
    for tgt, (regs, n) in cs.items():
        if any(a <= tgt < b for a, b in REAL) or tgt in done:
            continue
        if tgt in (0x60cfd27b, 0x607f9062):
            body = f' mov {OBJ},a0'
        elif tgt in (0x60ccf908, 0x60ccf94a):
            body = ' nop'
        else:
            body = ov.get(tgt, ' mov 0,d0')
        rg.append(Region('s%x' % tgt, tgt, asm(body + '\n' + retins(regs, n)), 'rx'))
        done.add(tgt)
    assert B.GETSID in cs and cs[B.GETSID] == ('d2,a2', 24) and cs[B.RULE if False else 0x60cc8be9] == ('d2,d3', 8)
    rg.append(Region('wrap', WRAP, b'\xdd' + struct.pack('<i', FN - WRAP) + bytes([0xf0, 56]) + b'\xcb', 'rx'))
    regs = dict(d0=ev, d1=cnt & 0xffffffff, a1=CTX, sp=SP0, pc=WRAP, d2=0x2222d2d2, d3=0x3333d3d3, a2=0x4444a2a2, a3=0x5555a3a3, mdr=0x77777777)
    return rg, regs


def run(img, *a, stop=WRAP + 7, **k):
    rg, regs = world(img, *a, **k)
    try:
        r = execute(rg, regs, stop, limit=6000, trace_limit=3000)
    except Exception as e:
        return dict(err=str(e))
    mem = {m['name']: bytes.fromhex(m['hex']) for m in r['memory']}
    reg = r['registers']
    sp = reg['sp']
    calls = [(hex(row['pc']), row['d0'], row['d1']) for row in r['trace'] if row['pc'] in GATED]
    lo = min(row['sp'] for row in r['trace']) if r['trace'] else sp
    ctxb = mem['ctx']
    return dict(status=r['status'], fault=r['fault'], reg=reg, calls=calls, ctx=ctxb, stack=mem['stack'][sp - STACK:] if STACK <= sp < STACK + 0x2000 else b'',
                c32=struct.unpack_from('<I', ctxb, 32)[0], c192=struct.unpack_from('<I', ctxb, 192)[0], c272=struct.unpack_from('<I', ctxb, 272)[0],
                c276=struct.unpack_from('<I', ctxb, 276)[0], minsp=lo, trace=r['trace'])


CMP_REGS = ['d0', 'd1', 'd2', 'd3', 'a0', 'a1', 'a2', 'a3', 'sp', 'mdr', 'psw']


def same(x, y, regs=CMP_REGS, skip=()):
    """-> list of differences between two run results (registers, calls, ctx, stack above sp). skip = byte range (lo, hi) of the stack slice not compared:
    at the resume point the slot (0,sp) of the routine (the slot a `call` stores its return address in) holds the return address of the last
    `call` (0x60cdc840 in stock, 0x60210937 with the stub); the next call (0x60cdc848) overwrites it and nothing reads it in between (E3)."""
    d = [r for r in regs if x['reg'][r] != y['reg'][r]]
    if x['calls'] != y['calls']:
        d.append('calls')
    if x['ctx'] != y['ctx']:
        d.append('ctx')
    cut = (lambda b: b[:skip[0]] + b[skip[1]:]) if skip else (lambda b: b)
    if cut(x['stack']) != cut(y['stack']):
        d.append('stack')
    return d


def good_run(r):
    return 'err' not in r and not r['fault'] and r['status'] == 'returned'


def stopped_ok(r):
    return 'err' not in r and not r['fault']


def key_of(s109, s24):
    return s109 if s109 != 0 else s24


# ------------------------------------------------------------------ E1 matrix
EV = [0x1010001, 0x1010002]
LAST = ('0x60ccf908', '0x60ccf94a')


def expected_fn(fn, key, lens):
    if key == 6 and fn == 3 and lens == 0:
        return 6
    if key == 6 and fn == 2 and lens != 0:
        return 3
    return fn


def e1(pat, quick=False):
    """-> (n cases, n target, [failures])"""
    stock, fails, n, nt = STOCK, [], 0, 0
    for fn, ev, cnt, key, lens, d2v, ceca in itertools.product([2, 3], EV, [1, -1], [3, 4, 5, 6], [0, 1], [9, 12, 13, 19], [0, 1]):
        if quick and (ceca or d2v == 13):
            continue
        a = (fn, ev, cnt, 0, key, key, lens, d2v, ceca)
        ef = expected_fn(fn, key, lens)
        s, p = run(stock, *((ef,) + a[1:])) if ef != 6 else None, run(pat, *a)
        n += 1
        for nm, r in (('stock', s), ('patched', p)):
            if r is not None and not good_run(r):
                fails.append(('RUN', nm, a, str(r.get('err') or (r.get('fault'), r.get('status')))[:80]))
        if not good_run(p) or (s is not None and not good_run(s)):
            continue
        if ef == 6:
            nt += 1
            lastc = [c for c in p['calls'] if c[0] in LAST]
            rule = [c for c in p['calls'] if c[0] == '0x60cc8be9']
            iso = [c for c in p['calls'] if c[0] == '0x60cde346']
            good = bool(rule) and rule[0][1] == 6 and p['reg']['sp'] == SP0 and bool(lastc) and lastc[-1][1] == 6
            if d2v in (9, 12, 13):
                good &= (p['c32'] == (215 if ev == 0x1010001 else 216) and p['c192'] == 0x5704 and p['reg']['d0'] == 0 and len(iso) == 1
                         and iso[0][1] == 6 and iso[0][2] == cnt & 0xffffffff and lastc[-1][0] == (LAST[0] if cnt > 0 else LAST[1]))
            if not good:
                fails.append(('TARGET', a, p['calls'], p['c32'], p['c192']))
        else:
            d = same(s, p)
            if d:
                fails.append(('STOCK-EQ', a, ef, d))
    return n, nt, fails


# ------------------------------------------------------------------ E2 oracle
def oracle_args(rnd):
    fn = rnd.choice([2, 3, 3, 3, 4, 5, 6, 9])
    key = rnd.choice([3, 4, 5, 6, 6, 6])
    mode = rnd.choice(['109', '109', '24', 'both'])
    s109, s24 = {'109': (key, rnd.choice([0, 3, 5, 6])), '24': (0, key), 'both': (key, rnd.choice([0, 3, 5, 6]))}[mode]
    return dict(fn=fn, ev=rnd.choice(EV), cnt=rnd.choice([1, -1, 2, -3]), s109=s109, s24=s24, s26=rnd.choice([0, 14, key, 6]),
                lens=rnd.choice([0, 0, 1, 2]), d2v=rnd.choice([3, 5, 9, 10, 12, 13, 19, 26, 21, 0]), ceca=rnd.choice([0, 1]),
                r75=rnd.choice([1, 1, 1, 0]), r20e9=rnd.choice([1, 1, 1, 0]), write=rnd.choice([0, 0, 0, 1]), a188=rnd.choice([0, 0, 0x5101, 1]))


def e2(pat, n, seed=7):
    rnd, fails, tgt = random.Random(seed), [], 0
    for _ in range(n):
        k = oracle_args(rnd)
        fn2 = expected_fn(k['fn'], key_of(k['s109'], k['s24']), k['lens'])
        tgt += fn2 != k['fn']
        p = {kk: vv for kk, vv in k.items()}
        q = dict(p, fn=fn2)
        pa = lambda d: tuple(d[x] for x in ('fn', 'ev', 'cnt', 's109', 's24', 's26', 'lens', 'd2v', 'ceca'))
        extra = dict(r75=k['r75'], r20e9=k['r20e9'], write=k['write'], a188=k['a188'])
        # end of the routine
        s, pp = run(STOCK, *pa(q), **extra), run(pat, *pa(p), **extra)
        if not (good_run(s) and good_run(pp)):
            fails.append(('RUN', k)); continue
        d = same(s, pp)
        if d:
            fails.append(('END', k, fn2, d)); continue
        # resume point 0x60cdc840 (before the rest of the routine)
        s, pp = run(STOCK, *pa(q), stop=RESUME, **extra), run(pat, *pa(p), stop=RESUME, **extra)
        if not (stopped_ok(s) and stopped_ok(pp)):
            fails.append(('RUNR', k)); continue
        d = same(s, pp, ['d0', 'd2', 'd3', 'a2', 'a3', 'sp', 'psw'], skip=(0, 4))
        if d or pp['reg']['pc'] != RESUME:
            fails.append(('RESUME', k, fn2, d))
    return fails, tgt


def e3(pat):
    """MDR: at the resume point (non-target and target) and at the end (non-target; target against stock with fn = 6)."""
    out = {}
    for nm, k, kref in (('non-target (fn 3, key 6, lens 1)', (3, EV[0], 1, 0, 6, 6, 1, 12, 1), None),
                        ('target (fn 3, key 6, lens 0) vs stock fn 6', (3, EV[0], 1, 0, 6, 6, 0, 12, 1), (6, EV[0], 1, 0, 6, 6, 0, 12, 1)),
                        ('target (fn 2, key 6, lens 1) vs stock fn 3', (2, EV[0], 1, 0, 6, 6, 1, 12, 1), (3, EV[0], 1, 0, 6, 6, 1, 12, 1))):
        r0s, r0p = run(STOCK, *(kref or k), stop=RESUME), run(pat, *k, stop=RESUME)
        r1s, r1p = run(STOCK, *(kref or k)), run(pat, *k)
        out[nm] = (r0s['reg']['mdr'], r0p['reg']['mdr'], r1s['reg']['mdr'], r1p['reg']['mdr'], r0s['reg']['sp'] == r0p['reg']['sp'] and r1s['reg']['sp'] == r1p['reg']['sp'])
    # static: the first instruction after the resume point that reads or writes MDR is a call (writes it)
    ins, _ = B.disasm(STOCK[RESUME - BASE:RESUME - BASE + 0x20], RESUME)
    first = [(hex(a_), op) for a_, op, _, _ in ins if op in ('call', 'calls', 'ret', 'retf', 'rets', 'mul', 'mulu', 'div', 'divu', 'jmp')][:1]
    return out, first


# ------------------------------------------------------------------ mutants
def mut_stub(code, old, new):
    assert code.count(bytes.fromhex(old)) == 1, old
    return code.replace(bytes.fromhex(old), bytes.fromhex(new))


def mutants(spec_img):
    code, jmp, *_ = B.build(STOCK)

    def with_stub(c, hook=jmp):
        d = bytearray(spec_img)
        d[AT - BASE:AT - BASE + len(c)] = c
        d[HOOK - BASE:HOOK_END - BASE] = hook
        return bytes(d)
    nop5 = b'\xcb' * 5
    out = {
        'lens polarity inverted (bne -> beq)': with_stub(mut_stub(code, 'a000c90abf03', 'a000c80abf03')),
        'mode key 6 -> 5': with_stub(mut_stub(code, 'a006c91c', 'a005c91c')),
        'first function 3 -> 4': with_stub(mut_stub(code, 'f1e3a003c806', 'f1e3a004c806')),
        'ISO 6 -> 9': with_stub(mut_stub(code, 'c90c9f06ca08', 'c90c9f09ca08')),
        'FNo. target 3 -> 4 (contact lens branch)': with_stub(mut_stub(code, 'bf02c9049f03', 'bf02c9049f04')),
        'exposure-comp test 2 -> 4': with_stub(mut_stub(code, 'bf02c904', 'bf04c904')),
        'no-lens function test dropped (everything ISO)': with_stub(mut_stub(code, 'bf03c90c', 'cbcbcbcb')),
        'FNo. assignment with contacts dropped': with_stub(mut_stub(code, '9f03f1dc', 'cbcbf1dc')),
        'hook shifted by 2 bytes': with_stub(code, b'\xdc' + struct.pack('<i', AT + 2 - HOOK) + b'\xcb' * 4),
        'stub without the resume jmp': with_stub(code.replace(code[-5:], nop5)),
        'sid 109 -> 108': with_stub(mut_stub(code, '806d', '806c')),
        'sid 24 fallback dropped': with_stub(mut_stub(code, 'a000c90b8018', 'a000ca0b8018')),
        'lens test dropped (always no lens)': with_stub(mut_stub(code, 'a000c90abf03', 'a000cbcbbf03')),
        'restore of d0 dropped': with_stub(mut_stub(code, 'f1dcdda9', 'cbcbdda9')),
        'ISO set into d0 only (a3 stays 3)': with_stub(mut_stub(code, 'c90c9f06ca08', 'c90c8006ca08')),
        'sid 24 only (109 ignored)': with_stub(mut_stub(code, '806d', '8018')),
    }
    return out


def quick_detect(img):
    n, nt, f = e1(img, quick=True)
    if f:
        return True
    f2, _ = e2(img, 80, seed=11)
    return bool(f2)


def main():
    global ok
    args = [x for x in sys.argv[1:] if not x.startswith('--')]
    dec = sys.argv[sys.argv.index('--decoded') + 1] if '--decoded' in sys.argv else None
    if dec and dec in args:
        args.remove(dec)
    spec_path = Path(args[0]) if args else HERE / 'edits.json'
    img = package(spec_path, dec)
    n, nt, f = e1(img)
    rep(f'E1 real routine 0x60cdc82c: {n} cases ({nt} ISO targets, the others identical to the stock run of the expected function)', not f, str(f[:3]) if f else '')
    ex = run(img, 3, EV[0], 1, 0, 6, 6, 0, 12, 1)
    exs = run(STOCK, 3, EV[0], 1, 0, 6, 6, 0, 12, 1)
    print('  example M / no lens / main dial / +1   stock  :', exs['calls'], 'c32', exs['c32'], 'a3', hex(exs['reg']['a3']))
    print('  example M / no lens / main dial / +1   patched:', ex['calls'], 'c32', ex['c32'], 'c192', hex(ex['c192']), 'c272', ex['c272'])
    exs = run(img, 3, EV[1], -1, 0, 6, 6, 0, 12, 0)
    print('  example M / no lens / sub dial / -1    patched:', exs['calls'], 'c32', exs['c32'])
    exg = run(img, 3, EV[0], 1, 0, 6, 6, 0, 19, 0)
    print('  example gate fails (d2 = 19)           patched:', exg['calls'], 'c32', exg['c32'])
    f2, tgt = e2(img, 600)
    rep(f'E2 oracle patched(fn) == stock(fn\'): 600 random combinations ({tgt} remapped: fn 3 -> 6 or fn 2 -> 3)', not f2, str(f2[:2]) if f2 else '')
    mdr, first = e3(img)
    good = bool(first) and first[0][1] == 'call' and all(a != b and c == d and sp for a, b, c, d, sp in mdr.values())
    rep('E3 MDR: differs at the resume point, identical at the end (sp identical); first MDR user after the resume point is a call', good,
        '; '.join(f'{k}: resume {a:#x}/{b:#x} end {c:#x}/{d:#x}' for k, (a, b, c, d, _) in mdr.items()) + f'; first {first}')
    for nm, mi in mutants(img).items():
        det = quick_detect(mi)
        rep(f'M mutant {nm}: DETECTED' if det else f'M mutant {nm}: NOT DETECTED', det)
    print('RESULT', 'PASS' if ok else 'FAIL')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
