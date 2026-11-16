#!/usr/bin/env python3
"""Emulator check of the E-P7 1.1 `lever_nomenu` patch (edits.json: 0x60cd4a0a  c9 -> ca).

startProfileSelect (0x60cd4830) is entered the way its caller does it: `call 0x60cd4830,[d2,d3,a2,a3],92`
(the call instruction builds the 92-byte frame; the routine has no prologue and ends in
`ret [d2,d3,a2,a3],92`).  Inputs: d0 = pointer to a byte/word the routine sets to 1 (caller's local, sp+28),
a1 = ctx (copied to a2); a0 is overwritten before any read.  Return value in d0.

Every external call in the routine is replaced by a stub placed AT THE FIRMWARE ADDRESS of the callee:
`mov imm,d0` (or `mov obj,a0` for the vtable-object getters) then the exact `ret [regs],N` read from the call
site.  The call sites are re-read from the disassembly at run time and must match the stub table, so a stub
frame cannot silently drift.  Unstubbed calls fault (unmapped execute).

Runs stock and patched (edits.json applied in memory only, nothing written) over the same synthetic state, then
checks: results, ctx diff, SP/d2/d3/a2/a3/MDR at exit, caller's stack frame untouched, order of external calls.
Mutation tests: the same checks run on images where the patch byte is reverted (c9) or wrong (c8) and MUST fail.

Usage: patches/lever_nomenu/verify.py          exit 0 = every case PASS and every mutation detected
"""
import json, re, struct, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools')); sys.path.insert(0, str(ROOT / 'external/oly_fw_analysis/tools'))
import ep7_color_probe as PR  # noqa: E402
from penf_emulator import Region  # noqa: E402

BASE = 0x60020020
FN, FN_END = 0x60cd4830, 0x60cd4aa0            # startProfileSelect (next function starts at 0x60cd4aa0)
SITE = 0x60cd4a0a
TAIL = 0x60cd4a71                              # bne/bra target: log, ccab96(3), log, return d3
CALLER_FN, CALLER_BEG, CALLER_END = 0x60cd2906, 0x60cd2ff7, 0x60cd3030   # startMoveToShootingReady, call site 0x60cd2fff
CALLER_FAIL, CALLER_OK = 0x60cd3008, 0x60cd301e   # after `cmp 0,d0; bne 0x60cd301e`
CALL, STACK, SP0 = PR.CALLER, PR.STACK, PR.STACK + 0x1800
CTX, OUT = 0x1a000000, 0x19000000
VT_BASE, METH_BASE = 0x1c000000, 0x1d000000
SENT = dict(d1=0x1111d1d1, d2=0x2222d2d2, d3=0x3333d3d3, a2=0x4444a2a2, a3=0x5555a3a3, mdr=0x6666dddd)
A0_IN = 0xa0a0a0a0
CTX_SIZE = 256

# External callee -> (kind, saved regs, frame N) exactly as at the call sites (cross-checked with objdump below).
# kind: 'd0' = returns a value in d0; 'obj:<name>' = returns a vtable object pointer in a0.
STUBS = {
    0x60cd234d: ('d0', '', 0),               # (8,sp) <- state code
    0x60cfbd9c: ('d0', 'd2,d3,a2,a3', 20),   # log (frame 20)
    0x60cfbc8a: ('d0', 'd2,a2,a3', 152),     # log (frame 152)
    0x60ccabeb: ('d0', 'd2,d3,a2', 28),
    0x60ccf2b6: ('d0', 'd2', 8),
    0x60cd20e9: ('d0', 'd2,d3,a2', 40),
    0x60ccf8ff: ('d0', '', 0),
    0x60cd644b: ('d0', 'd2,d3,a2', 24),
    0x60cd6436: ('d0', 'd2', 8),
    0x60cd241a: ('d0', 'd2,a2', 12),
    0x60cd244f: ('d0', 'd2,a2', 12),
    0x60cd170c: ('d0', 'd2,d3,a2', 28),
    0x60cd000e: ('d0', 'd2,d3,a2,a3', 32),
    0x60ccfe56: ('d0', 'd2,d3', 24),
    0x60ccfe44: ('d0', '', 0),
    0x60cce3dc: ('d0', 'd2,d3,a2,a3', 92),
    0x60ccac3e: ('d0', 'd2,d3,a2,a3', 64),
    0x60ccab96: ('d0', 'd2,d3', 24),         # records its arguments (via the trace)
    0x60cc9390: ('d0', '', 8),
    0x60ce5fba: ('d0', '', 0),
    0x60cd1a36: ('d0', 'd2,a2', 36),
    0x60cd00f8: ('d0', 'd2,d3', 24),
    0x60cd02cd: ('d0', 'd2,d3', 20),
    0x60cfd10f: ('obj:A', 'a2', 12),         # singleton: vtable+268 (request), vtable+140
    0x60cfd297: ('obj:B', 'a2', 12),         # singleton: vtable+600
    0x60cfd12b: ('obj:C', 'a2', 12),         # singleton: vtable+48
}
# vtable objects: name -> (object address, {vtable offset: method id})
OBJS = {'A': (VT_BASE + 0x000, {268: 'A268', 140: 'A140'}),
        'B': (VT_BASE + 0x010, {600: 'B600'}),
        'C': (VT_BASE + 0x020, {48: 'C48'})}
METHODS = ['A268', 'A140', 'B600', 'C48']          # each: mov imm,d0 ; rets   at METH_BASE + 16*i
VT_ADDR = {'A': VT_BASE + 0x100, 'B': VT_BASE + 0x500, 'C': VT_BASE + 0x900}
NAMES = {0x60cd234d: 'cd234d', 0x60cfbd9c: 'log20', 0x60cfbc8a: 'log152', 0x60ccabeb: 'ccabeb', 0x60ccf2b6: 'ccf2b6',
         0x60cd20e9: 'cd20e9', 0x60ccf8ff: 'ccf8ff', 0x60cd644b: 'cd644b', 0x60cd6436: 'cd6436', 0x60cd241a: 'cd241a',
         0x60cd244f: 'cd244f', 0x60cd170c: 'cd170c', 0x60cd000e: 'cd000e', 0x60ccfe56: 'ccfe56', 0x60ccfe44: 'ccfe44',
         0x60cce3dc: 'cce3dc', 0x60ccac3e: 'ccac3e', 0x60ccab96: 'ccab96', 0x60cc9390: 'cc9390', 0x60ce5fba: 'ce5fba',
         0x60cd1a36: 'cd1a36', 0x60cd00f8: 'cd00f8', 0x60cd02cd: 'cd02cd', 0x60cfd10f: 'objA', 0x60cfd297: 'objB',
         0x60cfd12b: 'objC'}
METH_ADDR = {m: METH_BASE + 16 * i for i, m in enumerate(METHODS)}
for m, a in METH_ADDR.items():
    NAMES[a] = 'vt:' + m
LOGS = {0x60cfbd9c, 0x60cfbc8a}


# ---------------------------------------------------------------- assembly helpers
_asm_cache = {}


def asm(text):
    if text in _asm_cache:
        return _asm_cache[text]
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        (t / 's.s').write_text('.am33_2\n.text\n' + text + '\n')
        subprocess.run([PR.TC / 'mn10300-elf-as', '-o', t / 's.o', t / 's.s'], check=True)
        subprocess.run([PR.TC / 'mn10300-elf-objcopy', '-O', 'binary', '-j', '.text', t / 's.o', t / 's.bin'], check=True)
        _asm_cache[text] = (t / 's.bin').read_bytes()
    return _asm_cache[text]


def stub_bytes(addr, ret):
    kind, regs, n = STUBS[addr]
    if kind == 'd0':
        return asm(f' mov {ret},d0\n ret [{regs}],{n}')
    return asm(f' mov {OBJS[kind[4:]][0]},a0\n ret [{regs}],{n}')


def method_bytes(ret):
    return asm(f' mov {ret},d0\n rets')


def crosscheck_call_sites(image):
    """Re-read every `call` in startProfileSelect from the disassembly; each must have a stub with the same frame."""
    d = PR.TC / 'mn10300-elf-objdump'
    p = Path(tempfile.mkdtemp()) / 'fn.bin'
    p.write_bytes(image)
    out = subprocess.run([d, '-b', 'binary', '-m', 'am33-2', '-D', f'--adjust-vma={BASE:#x}', f'--start-address={FN:#x}',
                          f'--stop-address={FN_END:#x}', p], capture_output=True, text=True, check=True).stdout
    found = {}
    for m in re.finditer(r'\tcall\s+0x([0-9a-f]+),\[([a-z0-9,]*)\],(\d+)', out):
        found.setdefault(int(m.group(1), 16), set()).add((m.group(2), int(m.group(3))))
    errs = []
    for tgt, frames in found.items():
        if tgt not in STUBS:
            errs.append(f'call to {tgt:#x} has no stub'); continue
        _, regs, n = STUBS[tgt]
        if frames != {(regs, n)}:
            errs.append(f'{tgt:#x}: site frames {sorted(frames)} != stub {(regs, n)}')
    unused = sorted(set(STUBS) - set(found))
    return found, errs, unused


# ---------------------------------------------------------------- scenarios
BASE_RV = {  # default stub results: reach 0x60cd4a0a with cce3dc(76) == 1
    0x60cd234d: 5,            # != 0x01000002 / 0x01000004
    0x60ccabeb: 1,            # nonzero (else early exit)
    0x60ccf2b6: 0,            # != 1 (d3)
    0x60cd20e9: 1,            # nonzero
    0x60ccf8ff: 1,            # nonzero (skips the 0x60cfd12b object test)
    0x60cd644b: 1,            # == d3
    0x60cd170c: 0, 0x60cd000e: 0, 0x60ccfe56: 0, 0x60ccfe44: 0,
    0x60cd6436: 1,            # == d3
    0x60cd241a: 0, 0x60cd244f: 0,
    0x60cce3dc: 1,            # the patched branch: == d3 -> request the list
    0x60ccac3e: 0, 0x60ccab96: 0, 0x60cc9390: 0, 0x60ce5fba: 0, 0x60cd1a36: 0, 0x60cd00f8: 0, 0x60cd02cd: 0,
    0x60cfbd9c: 0, 0x60cfbc8a: 0,
    'A268': 0, 'A140': 0, 'B600': 0, 'C48': 0,
}


def scen(**ov):
    rv = dict(BASE_RV)
    ctx196 = ov.pop('ctx196', 0)
    for k, v in ov.items():
        rv[int(k[1:], 16) if k.startswith('x') else k] = v
    return rv, ctx196


def fresh_ctx(ctx196=0):
    c = bytearray((i * 7 + 3) & 0xff for i in range(CTX_SIZE))
    struct.pack_into('<I', c, 192, 0x00001234)       # nonzero marker, != 0x5704
    struct.pack_into('<I', c, 32, 0x0badf00d); struct.pack_into('<I', c, 36, 0x0defaced)
    struct.pack_into('<I', c, 196, ctx196)
    return bytes(c)


def regions_for(image, rv, ctx196, *, caller_mode=False):
    regs_ = [Region('stack', STACK, bytes(0x2000), 'rw', True),
             Region('fn', FN, image[FN - BASE:FN_END - BASE], 'rx'),
             Region('ctx', CTX, fresh_ctx(ctx196), 'rw', True),
             Region('out', OUT, bytes(16), 'rw', True)]
    if caller_mode:
        regs_.append(Region('realcaller', CALLER_BEG, image[CALLER_BEG - BASE:CALLER_END - BASE], 'rx'))
    else:
        regs_.append(Region('caller', CALL, b'\xdd' + struct.pack('<i', FN - CALL) + bytes((0xf0, 92)) + b'\xcb', 'rx'))
    for a in STUBS:
        regs_.append(Region(f's_{a:x}', a, stub_bytes(a, rv[a] if STUBS[a][0] == 'd0' else 0), 'rx'))
    vt = bytearray(0x1000)
    for name, (oaddr, ents) in OBJS.items():
        struct.pack_into('<I', vt, oaddr - VT_BASE, VT_ADDR[name])
        for off, m in ents.items():
            struct.pack_into('<I', vt, VT_ADDR[name] - VT_BASE + off, METH_ADDR[m])
    regs_.append(Region('vtables', VT_BASE, bytes(vt), 'r'))
    meth = bytearray(16 * len(METHODS))
    for m, a in METH_ADDR.items():
        b = method_bytes(rv[m]); meth[a - METH_BASE:a - METH_BASE + len(b)] = b
    regs_.append(Region('methods', METH_BASE, bytes(meth), 'rx'))
    return regs_


def run(image, rv, ctx196=0, *, caller_mode=False):
    regs = dict(SENT, sp=SP0, d0=OUT, a0=A0_IN, a1=CTX)
    if caller_mode:       # real caller code from 0x60cd2ff7: a3 = ctx, (8,sp) = a0 argument, a2 set by the caller itself
        regs.update(pc=CALLER_BEG, a3=CTX, d0=0)
    else:
        regs['pc'] = CALL
    rg = regions_for(image, rv, ctx196, caller_mode=caller_mode)
    if caller_mode:
        for r in rg:
            if r.name == 'stack':
                b = bytearray(r.data); struct.pack_into('<I', b, 0x1800 + 8, A0_IN)
                rg[rg.index(r)] = Region('stack', STACK, bytes(b), 'rw', True)
        res = PR.execute(rg, regs, 0xdead0000, limit=20000, trace_limit=4000, breakpoints=[CALLER_FAIL, CALLER_OK])
    else:
        res = PR.execute(rg, regs, CALL + 7, limit=20000, trace_limit=4000)
    mem = {m['name']: bytes.fromhex(m['hex']) for m in res['memory']}
    calls = []                                   # external calls in order: (name, d0 at entry, d1 at entry)
    for row in res['trace']:
        if row['pc'] in NAMES and (row['pc'] in STUBS or row['pc'] in METH_ADDR.values()):
            calls.append((NAMES[row['pc']], row['d0'], row['d1']))
    return dict(res=res, r=res['registers'], mem=mem, calls=calls, ctx=mem['ctx'], out=mem['out'], stack=mem['stack'])


def ctx_diff(c):
    base = fresh_ctx(struct.unpack_from('<I', c, 196)[0])
    return {o: struct.unpack_from('<I', c, o)[0] for o in range(0, CTX_SIZE, 4)
            if c[o:o + 4] != base[o:o + 4]}


# ---------------------------------------------------------------- checks
def common_invariants(x, caller_mode=False):
    """Calling-convention invariants that must hold for every run, stock or patched."""
    errs, r = [], x['r']
    if x['res']['fault']:
        errs.append(f"fault {x['res']['fault']}")
    want_status = 'breakpoint' if caller_mode else 'returned'
    if x['res']['status'] != want_status:
        errs.append(f"status {x['res']['status']}")
    if not caller_mode and r['pc'] != CALL + 7:
        errs.append(f"pc {r['pc']:#x}")
    if r['sp'] != SP0:
        errs.append(f"SP {r['sp']:#x} != {SP0:#x} (stack unbalanced by {r['sp'] - SP0:+d})")
    for k in ('d2', 'd3') + (() if caller_mode else ('a2', 'a3')):
        if r[k] != SENT[k]:
            errs.append(f'{k} {r[k]:#x} != entry {SENT[k]:#x}')
    if caller_mode and r['a3'] != CTX:
        errs.append(f"a3 {r['a3']:#x} != ctx {CTX:#x}")
    # MDR: the emulator (and FIRMWARE_GUIDE s9) set MDR := return address on every call and `ret` does not restore it,
    # so MDR != entry value for ANY routine that makes a call.  Invariant used instead: MDR == return address of the
    # last call executed, and stock/patched must agree (compared in the cases).
    last_ret = None
    for row in x['res']['trace']:
        if row['pc'] in STUBS or row['pc'] in METH_ADDR.values():
            last_ret = row['mdr']          # MDR at stub entry == return address of that call
    if last_ret is not None and r['mdr'] != last_ret:
        errs.append(f"mdr {r['mdr']:#x} != return address of last call {last_ret:#x}")
    # the caller's frame above SP must be byte-identical to what we put there
    init = bytearray(0x2000)
    if caller_mode:
        struct.pack_into('<I', init, 0x1800 + 8, A0_IN)
    if not caller_mode and x['stack'][0x1804:] != bytes(init[0x1804:]):
        errs.append('caller stack frame (> SP+3) modified')
    return errs


def expect_main(x_stock, x_patch):
    errs = []
    s, p = x_stock, x_patch
    if s['r']['d0'] != 0: errs.append(f"stock d0={s['r']['d0']} (want 0)")
    if ctx_diff(s['ctx']) != {192: 0x5704, 32: 183, 36: 4}: errs.append(f"stock ctx diff {ctx_diff(s['ctx'])}")
    if 'objA' not in [c[0] for c in s['calls']] or 'vt:A268' not in [c[0] for c in s['calls']]:
        errs.append('stock did not call the vtable object (+268)')
    if p['r']['d0'] != 1: errs.append(f"patched d0={p['r']['d0']} (want 1)")
    if ctx_diff(p['ctx']):  errs.append(f"patched ctx changed {ctx_diff(p['ctx'])}")
    c96 = [c for c in p['calls'] if c[0] == 'ccab96']
    if len(c96) != 1 or c96[0][1] != 3: errs.append(f'patched ccab96 calls {c96}')
    if [c for c in p['calls'] if c[0] in ('objA', 'objB', 'vt:A268', 'vt:A140') and c[0] != 'objB']:
        errs.append('patched still calls the objA vtable')
    if [c for c in s['calls'] if c[0] == 'ccab96']:
        pass  # stock may or may not reach it; not asserted
    # patched sequence must be stock's sequence up to the 0x60cce3dc(76) call, then the TAIL calls
    i = [c[0] for c in s['calls']].index('cce3dc')
    if s['calls'][:i + 1] != p['calls'][:i + 1]: errs.append('call sequences diverge before the patch site')
    if [c for c in s['calls'] if c[0] == 'cce3dc'][0][1] != 76: errs.append('cce3dc not called with 76')
    if s['out'] != p['out']: errs.append('out byte differs')
    if s['r']['mdr'] != p['r']['mdr']: errs.append(f"mdr stock {s['r']['mdr']:#x} != patched {p['r']['mdr']:#x}")
    return errs


def fmt(x):
    r = x['r']
    return f"d0={r['d0']} ctx+192={struct.unpack_from('<I', x['ctx'], 192)[0]:#x} +32={struct.unpack_from('<I', x['ctx'], 32)[0]:#x} " \
           f"+36={struct.unpack_from('<I', x['ctx'], 36)[0]:#x} out={x['out'][0]} sp-SP0={r['sp'] - SP0:+d}"


def apply_edits(stock, edits_json, override_new=None):
    d = bytearray(stock)
    for e in json.loads(edits_json.read_text())['edits']:
        a = int(e['addr'], 16) - BASE
        exp, new = bytes.fromhex(e['expect']), bytes.fromhex(override_new or e['new'])
        assert d[a:a + len(exp)] == exp, f"{e['addr']}: expect {exp.hex()} found {d[a:a + len(exp)].hex()}"
        d[a:a + len(new)] = new
    return bytes(d)


def run_cases(stock, patched, verbose=True):
    results = []

    def rec(name, errs, detail=''):
        results.append((name, not errs))
        if verbose:
            print(f"{'PASS' if not errs else 'FAIL'} {name}" + (f'  [{detail}]' if detail else ''))
            for e in errs:
                print('       - ' + e)

    # --- MAIN: the patched branch is reached, 76 -> 1
    for m268 in (0, 1):
        rv, c196 = scen(A268=m268)
        s, p = run(stock, rv, c196), run(patched, rv, c196)
        errs = common_invariants(s) + [f'patched: {e}' for e in common_invariants(p)] + expect_main(s, p)
        rec(f'MAIN cce3dc(76)=1, vtable+268 returns {m268}: stock list-request -> patched fall to 0x60cd4a71', errs,
            f'stock {fmt(s)} | patched {fmt(p)}')
        if m268 == 0:
            MAIN = (s, p)
    s, p = MAIN
    print('       stock   calls: ' + ' '.join(c[0] for c in s['calls'] if c[0] not in ('log20', 'log152')))
    print('       patched calls: ' + ' '.join(c[0] for c in p['calls'] if c[0] not in ('log20', 'log152')))
    print(f"       patched ccab96 args: d0={[c for c in p['calls'] if c[0]=='ccab96'][0][1]} d1={[c for c in p['calls'] if c[0]=='ccab96'][0][2]:#x}")
    print(f"       registers at exit  stock: " + ' '.join(f"{k}={s['r'][k]:#x}" for k in ('sp', 'd2', 'd3', 'a2', 'a3', 'mdr')))
    print(f"       registers at exit  patch: " + ' '.join(f"{k}={p['r'][k]:#x}" for k in ('sp', 'd2', 'd3', 'a2', 'a3', 'mdr')))

    # --- identical-behaviour witnesses
    def same_case(name, ov, want_d0=None, note=''):
        rv, c196 = scen(**ov)
        s, p = run(stock, rv, c196), run(patched, rv, c196)
        errs = common_invariants(s) + [f'patched: {e}' for e in common_invariants(p)]
        for k in ('d0', 'sp', 'd2', 'd3', 'a2', 'a3', 'mdr'):
            if s['r'][k] != p['r'][k]: errs.append(f"{k}: stock {s['r'][k]:#x} != patched {p['r'][k]:#x}")
        if s['ctx'] != p['ctx']: errs.append(f'ctx differs {ctx_diff(s["ctx"])} vs {ctx_diff(p["ctx"])}')
        if s['out'] != p['out']: errs.append('out differs')
        if s['stack'] != p['stack']: errs.append('stack region differs')
        if s['calls'] != p['calls']: errs.append('call sequence differs')
        if want_d0 is not None and s['r']['d0'] != want_d0: errs.append(f"d0={s['r']['d0']} want {want_d0}")
        if 'cce3dc' in note and not any(c[0] == 'cce3dc' for c in s['calls']): errs.append('guard not reached')
        rec(name, errs, f'{fmt(s)}')
        return s

    same_case('WITNESS cce3dc(76)=0 -> stock == patched', {'x60cce3dc': 0}, 1, 'cce3dc')
    # early exits (each guard forced to its exiting value); the patch site must NOT be reached
    early = [('ccabeb=0', {'x60ccabeb': 0}, 1), ('ccf2b6=1', {'x60ccf2b6': 1}, 1), ('cd20e9=0', {'x60cd20e9': 0}, 1),
             ('ccf8ff=0 & objC+48 != 0', {'x60ccf8ff': 0, 'C48': 1}, 1), ('cd644b!=1 (jmp 0x60cd4a8b)', {'x60cd644b': 0}, 1),
             ('cd000e=1 (writes 0x5109/174, returns 0)', {'x60cd000e': 1}, 0), ('cd6436!=1', {'x60cd6436': 0}, 1),
             ('cd241a!=0', {'x60cd241a': 1}, 1), ('cd244f!=0', {'x60cd244f': 1}, 1),
             ('cd234d==0x01000002', {'x60cd234d': 0x01000002}, 1), ('cd234d==0x01000004', {'x60cd234d': 0x01000004}, 1)]
    for nm, ov, d0 in early:
        s = same_case(f'EARLY {nm} -> stock == patched', ov, d0)
        if any(c[0] == 'cce3dc' for c in s['calls']):
            rec(f'EARLY {nm}: patch site not reached', ['cce3dc was called'])
    # path variants that still reach the patch site: patched must still behave as MAIN
    for nm, ov in [('ctx+196==0x5a02 (cc9390/ce5fba)', {'ctx196': 0x5a02}), ('cd170c!=0 (cd1a36)', {'x60cd170c': 1}),
                   ('ccfe56==1, ccfe44==1 (cd00f8)', {'x60ccfe56': 1, 'x60ccfe44': 1}),
                   ('ccfe56==1, ccfe44!=1 (cd02cd)', {'x60ccfe56': 1, 'x60ccfe44': 0})]:
        rv, c196 = scen(**ov)
        s, p = run(stock, rv, c196), run(patched, rv, c196)
        errs = common_invariants(s) + [f'patched: {e}' for e in common_invariants(p)] + expect_main(s, p)
        rec(f'VARIANT {nm}: still stock list-request / patched fall-through', errs)
    return results


def run_caller_layer(stock, patched):
    """The REAL caller code (0x60cd2ff7..) around the call: shows what each return value does downstream."""
    rv, c196 = scen()
    out = []
    for nm, img in (('stock', stock), ('patched', patched)):
        x = run(img, rv, c196, caller_mode=True)
        errs = common_invariants(x, caller_mode=True)
        out.append((nm, x, errs))
    (sn, sx, se), (pn, px, pe) = out
    errs = se + pe
    if sx['r']['pc'] != CALLER_FAIL: errs.append(f"stock stopped at {sx['r']['pc']:#x}, want {CALLER_FAIL:#x} (ret 0 branch)")
    if px['r']['pc'] != CALLER_OK: errs.append(f"patched stopped at {px['r']['pc']:#x}, want {CALLER_OK:#x} (ret != 0 branch)")
    print(f"{'PASS' if not errs else 'FAIL'} CALLER real startMoveToShootingReady bytes 0x60cd2ff7..: "
          f"stock -> {sx['r']['pc']:#x} (d0={sx['r']['d0']}), patched -> {px['r']['pc']:#x} (d0={px['r']['d0']})")
    for e in errs:
        print('       - ' + e)
    return not errs


def main():
    stock = PR.main_image()
    edits = ROOT / 'patches/lever_nomenu/edits.json'
    patched = apply_edits(stock, edits)
    diff = [i for i in range(len(stock)) if stock[i] != patched[i]]
    ok = diff == [SITE - BASE] and stock[SITE - BASE] == 0xc9 and patched[SITE - BASE] == 0xca
    print(f"{'PASS' if ok else 'FAIL'} image diff: {[hex(i + BASE) for i in diff]}  {stock[SITE-BASE]:02x}->{patched[SITE-BASE]:02x}; "
          f"branch operand {stock[SITE-BASE+1]:#x} -> target {SITE + stock[SITE-BASE+1]:#x} (want {TAIL:#x})")
    ok &= SITE + stock[SITE - BASE + 1] == TAIL
    found, errs, unused = crosscheck_call_sites(stock)
    print(f"{'PASS' if not errs else 'FAIL'} call-site frames == stub table ({len(found)} distinct callees; unused stubs: {[hex(u) for u in unused]})")
    for e in errs: print('       - ' + e)
    if errs:
        sys.exit(1)
    ok &= not errs
    res = run_cases(stock, patched)
    ok &= all(g for _, g in res)
    ok &= run_caller_layer(stock, patched)
    # mutation tests: each broken patch MUST be rejected by the MAIN check
    print('--- mutation tests (each must be detected = FAIL of the MAIN check)')
    rv, c196 = scen()
    s = run(stock, rv, c196)
    for label, nb in (('revert to c9 (no patch)', 'c9'), ('beq c8 instead of bra', 'c8')):
        mut = apply_edits(stock, edits, override_new=nb) if nb != 'c9' else stock
        p = run(mut, rv, c196)
        errs = common_invariants(p) + expect_main(s, p)
        rv0, c0 = scen(x60cce3dc=0)          # witness: 76 -> 0 (a bra is indifferent, a beq/revert is not)
        s0, p0 = run(stock, rv0, c0), run(mut, rv0, c0)
        if s0['r']['d0'] != p0['r']['d0'] or s0['ctx'] != p0['ctx'] or s0['calls'] != p0['calls']:
            errs.append('witness cce3dc(76)=0: mutated != stock')
        det = bool(errs)
        ok &= det
        print(f"{'PASS' if det else 'FAIL'} mutation {label}: {'detected' if det else 'NOT DETECTED'} ({len(errs)} violations, e.g. {errs[0] if errs else '-'})")
    print('RESULT', 'PASS' if ok else 'FAIL')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
