#!/usr/bin/env python3
"""Static + model verification of patches/jpeg_always (no emulator needed). docs/JPEG_ALWAYS.md.

  python3 -I patches/jpeg_always/verify.py releases/v0.29a/edits.json generated/jpeg_always/edits.json
  python3 -I patches/jpeg_always/verify.py stock generated/jpeg_always_stock/edits.json        # --base stock build

Parts:
  S  static: sites, claim, forbidden opcodes, no store, alignment, call forms, sections, abs32 / rel32 references,
     CODE_SPACE_MAP.md rows and every releases/*/edits.json against this patch's edits
  D  diff: the patched main image differs from the base image only in this patch's bytes (+ the fw_version label)
  M  model: the REAL assembled bytes (disassembled by objdump, then interpreted by a tiny AM33 subset interpreter) run
     between a modelled site frame and a modelled getter / accessor, over the whole input matrix, and are compared with
     the stock call. It checks logic, stack balance, d2/d3 restore and register contract; it does NOT model MDR, PSW,
     the cache or the real getter (an emulator run is still wanted: docs/JPEG_ALWAYS.md section 6).
  L  loader (v0.29a build only): span[52] of the patched image is 1, lo[52] is 0, so a BUNDLES.BIN with +52 in {0,1} is still accepted
     (migration from jpeg_only); in the stock build the loader region is untouched.
Exit code 0 = all parts pass.
"""
import itertools, json, re, struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build as B  # noqa: E402

BASE = B.BASE
FAILS = []


def check(cond, what):
    if not cond:
        FAILS.append(what)
        print('FAIL', what)
    return cond


# ---------------------------------------------------------------------------- model
class Machine:
    GETTER = B.GETTER

    d1mode = 'idx'

    def __init__(self, ins, props, sentinel=None):
        self.prog = {a: (op, args) for a, op, args in ins}
        self.props = props
        self.calls = []                                   # (kind, key, idx, a0) per modelled external call
        self.frames = []
        self.reg = {}
        self.trace = []

    def val(self, tok):
        tok = tok.strip()
        if tok in self.reg:
            return self.reg[tok]
        return int(tok, 0)

    @staticmethod
    def parse_regs(s):
        m = re.fullmatch(r'\[(.*)\],(\d+)', s.strip())
        return [r for r in m.group(1).split(',') if r], int(m.group(2))

    def ret_to(self):
        regs, n, saved, ret = self.frames.pop()
        for r, v in zip(regs, saved):
            self.reg[r] = v
        return ret

    def external(self, target):
        r = self.reg
        if target == self.GETTER:
            key, idx, a0 = r['d0'] & 0xffff, r['d1'] & 0xffff, r['a0']        # the getter zero-extends key and idx
            self.calls.append(('get', key, idx, a0))
            r['d0'] = self.props.get((key, idx), 0) & 0xff
            r['d1'] = idx if self.d1mode == 'idx' else 0x77                    # the model getter may or may not leave d1 = idx
            r['a1'] = 0x5000 + key
            r['a0'] = 0x7000 + key
        else:
            raise AssertionError(f'unknown call target {target:#x}')
        return self.ret_to()

    def run(self, start, site_ret, init, site_saved):
        """init: registers at entry; the site frame (d2, d3 saved) is pushed first, as `call getter,[d2,d3],12` did."""
        self.reg = dict(init)
        self.reg['sp'] = 0
        self.frames = [(['d2', 'd3'], 12, site_saved, site_ret)]
        pc, z, steps = start, False, 0
        while pc != site_ret:
            steps += 1
            assert steps < 500, 'runaway'
            op, args = self.prog[pc]
            nxt = pc + self.size[pc]
            r = self.reg
            if op == 'mov':
                s, d = [x.strip() for x in args.split(',')]
                r[d] = self.val(s) & 0xffffffff
            elif op == 'nop':
                pass
            elif op == 'clr':
                r[args.strip()] = 0
            elif op == 'exth':
                v = r[args.strip()] & 0xffff
                r[args.strip()] = (v | 0xffff0000) if v & 0x8000 else v
            elif op == 'exthu':
                r[args.strip()] = r[args.strip()] & 0xffff
            elif op == 'cmp':
                s, d = [x.strip() for x in args.split(',')]
                a, b = int(s, 0) & 0xffffffff, r[d] & 0xffffffff
                z = a == b
            elif op in ('beq', 'bne', 'bra'):
                t = int(args, 0)
                if op == 'bra' or (op == 'beq') == z:
                    nxt = t
            elif op == 'call':
                tgt, rest = args.split(',', 1)
                tgt = int(tgt, 0)
                regs, n = self.parse_regs(rest)
                self.frames.append((regs, n, [r[x] for x in regs], nxt))
                self.trace.append(('call', tgt))
                if tgt == self.GETTER:
                    nxt = self.external(tgt)
                else:
                    nxt = tgt
            elif op == 'jmp':
                tgt = int(args, 0)
                self.trace.append(('jmp', tgt))
                nxt = self.external(tgt) if tgt == self.GETTER else tgt
            elif op == 'ret':
                regs, n = self.parse_regs(args)
                f = self.frames[-1]
                assert f[0] == regs and f[1] == n, f'ret {args} does not match the frame {f[0]},{f[1]}'
                nxt = self.ret_to()
            else:
                raise AssertionError(f'op {op} not modelled')
            pc = nxt
        assert not self.frames, f'stack not balanced at the site return: {len(self.frames)} frames left'
        return self.reg


def interp_setup(ins, code_len):
    size, prev = {}, None
    addrs = [a for a, _, _ in ins] + [B.AT + code_len]
    for a, b in zip(addrs, addrs[1:]):
        size[a] = b - a
    return size


def model(spec, sites_wanted):
    sdict = {hex(int(e['addr'], 16)): e for e in spec['edits'] if not e['addr'].startswith('off:')}
    code = bytes.fromhex(sdict[hex(B.AT)]['new'])
    ins = B.SB3.disasm(code, B.AT, B.AT + len(code))
    syms = {k: int(v, 16) for k, v in spec['jpeg_always']['symbols'].items()}
    n = 0
    sel_vals = [0, 1, 2, 3, 4, 5, 255]
    mode_vals = [0, 1, 2, 6, 11, 12, 13, 255]
    pm6_vals = [0, 6, 11, 12, 13]
    flag_vals = [0, 1, 2]
    for key, idx, d1mode in itertools.product((B.K_FLAG1, B.K_FLAG2, 0x1234, B.K_SEL1), (0, 5), ('idx', 'const')):
        selkey = B.K_SEL1 if key == B.K_FLAG1 else B.K_SEL2
        for sel, mode, pm6, flag, other_sel in itertools.product(sel_vals, mode_vals, pm6_vals, flag_vals, (0, 4)):
            if idx and (sel not in (0, 3) or mode not in (6, 11, 13) or pm6 not in (0, 12) or other_sel):
                continue                      # idx != 0 never happens at the sites; a reduced matrix is enough to pin d1 / idx handling
            props = {(B.K_SEL1, 0): sel if key != B.K_FLAG2 else other_sel, (B.K_SEL2, 0): sel if key == B.K_FLAG2 else other_sel,
                     (B.K_PMODE, 0): mode, (B.K_PMODE6, 0): pm6, (key, idx): flag, (B.K_FLAG1, 0): flag, (B.K_FLAG2, 0): flag}
            # stock: the site's own call straight into the getter
            init = dict(d0=key, d1=idx, a0=0, a1=0xa1a1, a2=0xa2a2, a3=0xa3a3, d2=0xd2d2, d3=0xd3d3)
            saved = [0xd2d2d2d2, 0xd3d3d3d3]
            st = Machine([], props)
            st.d1mode = d1mode
            st.prog, st.size = {}, {}
            st.reg = dict(init, sp=0)
            st.frames = [(['d2', 'd3'], 12, saved, 0xfffff)]
            st.external(B.GETTER)
            stock = dict(st.reg)
            m = Machine(ins, props)
            m.d1mode = d1mode
            m.size = interp_setup(ins, len(code))
            got = m.run(B.AT, 0xfffff, init, saved)
            rsel = props[(selkey, 0)] if key in (B.K_FLAG1, B.K_FLAG2) else None
            eff = pm6 if mode == 6 else mode
            want_override = key in (B.K_FLAG1, B.K_FLAG2) and rsel not in (3, 4) and eff in (11, 12)
            exp = dict(stock)
            if want_override:
                exp['d0'] = 0
            if not check(got == exp, f'key {key:#x} sel {rsel} mode {mode}/{pm6} flag {flag}: got {got} want {exp}'):
                return n
            kinds = [c[0] for c in m.calls]
            if key not in (B.K_FLAG1, B.K_FLAG2):
                check(m.calls == [('get', key, idx, 0)], f'foreign key {key:#x}: calls {m.calls}')
            else:
                last = m.calls[-1]
                check(last == ('get', key, idx, 0), f'last call is not the site\'s own getter call: {m.calls}')
                check(kinds.count('tbl') == 0 and set(kinds) == {'get'}, f'a non-getter call (SD accessor?): {m.calls}')
                check(all(c[3] == 0 for c in m.calls if c[0] == 'get'), 'a getter call with a0 != 0')
                check({c[1] for c in m.calls if c[0] == 'get'} <= {key, selkey, B.K_PMODE, B.K_PMODE6}, f'unexpected property read: {m.calls}')
                check(all(c[2] == 0 for c in m.calls[:-1] if c[0] == 'get'), 'a property read with idx != 0')
            n += 1
    return n


# ---------------------------------------------------------------------------- static + diff
def codespace_overlaps():
    txt = (ROOT / 'docs/CODE_SPACE_MAP.md').read_text()
    out = []
    for line in txt.splitlines():
        if 'jpeg_only' in line or 'jpeg_always' in line:      # jpeg_only is the alternative with option: same claim by design, never both
            continue
        for m in re.finditer(r'0x([0-9a-f]{8})\s*[–-]\s*0x([0-9a-f]{8})', line):
            if line[:m.start()].rstrip().endswith('keep'):      # prose: "keep 0x601de33c–0x601dfc3c between them" (a corridor, not a claim)
                continue
            lo, hi = int(m.group(1), 16), int(m.group(2), 16)
            if lo < B.END and B.AT < hi:
                out.append((hex(lo), hex(hi), line[:80]))
    return out


def releases_overlaps(own, loader_ok=True):
    """Every edit of every releases/*/edits.json against this patch's own spans (not the shared loader edit)."""
    spans = []
    for e in own:
        a, n = int(e['addr'], 16), len(e['new']) // 2
        spans.append((a, a + n, e['why'][:40]))
    bad = []
    for f in sorted((ROOT / 'releases').glob('*/edits.json')) + sorted((ROOT / 'patches').glob('*/edits.json')):
        for e in json.loads(f.read_text())['edits']:
            if e['addr'].startswith('off:'):
                continue
            a, n = int(e['addr'], 16), len(e['new']) // 2
            for lo, hi, w in spans:
                if a < hi and lo < a + n:
                    bad.append((str(f.relative_to(ROOT)), e['addr'], w))
    return bad


def main():
    stock_base = sys.argv[1] == 'stock'
    base_spec = {'components': ['0x100', '0x101'], 'edits': []} if stock_base else json.loads(Path(sys.argv[1]).read_text())
    spec = json.loads(Path(sys.argv[2]).read_text())
    stock = B.STOCK.read_bytes()
    meta = spec['jpeg_always']
    check(meta['base'] == ('stock' if stock_base else 'release'), 'spec base does not match the base argument')
    # ---- S
    own = [e for e in spec['edits'] if e.get('source') == B.SRC]
    check(len(own) == 1 + len(meta['sites']), f'{len(own)} own edits, expected 1 + {len(meta["sites"])}')
    code_e = [e for e in own if int(e['addr'], 16) == B.AT][0]
    code = bytes.fromhex(code_e['new'])
    check(B.AT % 4 == 0 and B.AT + len(code) <= B.END, 'code does not fit the claim / is not 4-aligned')
    check(bytes.fromhex(code_e['expect']) == stock[B.AT - BASE:B.AT - BASE + len(code)], 'code expect != stock')
    ins = B.SB3.disasm(code, B.AT, B.AT + len(code))
    while len(ins) > 1 and ins[-1][1] != 'ret' and code[ins[-1][0] - B.AT:] == bytes(len(code) - (ins[-1][0] - B.AT)):
        ins.pop()                                         # .balign 4 pads the end with zero bytes after the last ret (unreachable)
    check(code[ins[-1][0] - B.AT + 3:] == bytes(len(code) - (ins[-1][0] - B.AT + 3)), 'non-zero padding after the last ret')
    check(not [op for _, op, _ in ins if op in B.BAD], 'forbidden opcode')
    check(not any(code[a - B.AT] == 0xfb for a, _, _ in ins), 'fb-prefixed form')
    check(not B.SB3.store_audit(ins), 'store instruction in the stub')
    check(not any(op in ('movm', 'mul', 'div') for _, op, _ in ins), 'movm / mul / div')
    check(ins[-1][1] == 'ret', 'the last instruction is not a ret')
    check(sorted(a for a, _, _ in ins)[0] == B.AT, 'first instruction is not at the entry')
    # branch targets stay inside the stub, call targets are the stub itself or the stock getter
    inside = {a for a, _, _ in ins}
    for a, op, args in ins:
        if op in ('beq', 'bne', 'bra'):
            check(int(args, 0) in inside, f'{a:#x} branch leaves the stub')
        if op in ('call', 'jmp'):
            t = int(args.split(',')[0], 0)
            check(t in inside or t == B.GETTER, f'{a:#x} {op} to {t:#x}')
            check(t != B.TBL_OFF, f'{a:#x} calls the SD accessor')
    for e in own:
        a = int(e['addr'], 16)
        if a == B.AT:
            continue
        site = a - 1
        check(stock[site - BASE] == 0xdd and bytes.fromhex(e['expect']) == stock[a - BASE:a + 4 - BASE], f'site {site:#x} expect')
        check(site + struct.unpack('<i', bytes.fromhex(e['new']))[0] == B.AT, f'site {site:#x} target != jo_get')
        check(stock[a + 4 - BASE:a + 6 - BASE] == b'\xc0\x0c', f'site {site:#x} frame')
    print(f'S: {len(ins)} instructions, {len(code)} B, sites {meta["sites"]}')
    check(not codespace_overlaps(), f'CODE_SPACE_MAP overlap: {codespace_overlaps()}')
    check(not releases_overlaps(own), f'release / patch edit overlap: {releases_overlaps(own)}')
    # references into the claim in the patched image (abs32 both aliases, jmp/call d32)
    im = B.img_of(spec, stock)
    bim = B.img_of(base_spec, stock)
    refs = B.abs32_hits(im, B.AT, B.END)
    check(not refs, f'abs32 into the claim in the patched image: {[(hex(a), hex(v)) for a, v in refs]}')
    jr = [(hex(a), hex(t)) for a, t in B.rel32_hits(im, B.AT, B.END) if a != B.AT and not (B.AT <= a < B.AT + len(code))]
    sites = {int(s, 16) - 1 for s in meta['sites']}
    jr = [x for x in jr if int(x[0], 16) not in sites]
    check(not jr, f'jmp/call d32 into the claim from outside this patch: {jr}')
    check(B.section(B.AT) == 1, 'sections')
    B.check_sections()
    # ---- D
    diff = [i for i in range(len(im)) if im[i] != bim[i]]
    allowed = set()
    for e in own:
        a = int(e['addr'], 16) - BASE
        allowed.update(range(a, a + len(e['new']) // 2))
    if not stock_base:
        allowed.add(B.SPAN_52 - BASE)
    fvs = [e for e in spec['edits'] if e.get('source') == 'patches/fw_version']
    for e in fvs:
        a = int(e['addr'], 16) - BASE
        allowed.update(range(a, a + len(e['new']) // 2))
    stray = [hex(BASE + i) for i in diff if i not in allowed]
    check(not stray, f'bytes differ from the base outside this patch: {stray[:10]}')
    if stock_base:
        check(im[B.RANGE - 64 - BASE:B.RANGE + 64 - BASE] == stock[B.RANGE - 64 - BASE:B.RANGE + 64 - BASE], 'loader region touched in the stock build')
        check(not meta['loader_span'] and not fvs, 'stock build carries a loader edit or a version label')
    else:
        # L: migration. The patched loader still accepts BUNDLES.BIN with +52 in {0,1}: span[52] = 1, lo[52] = 0
        check(im[B.SPAN_52 - BASE] == 1 and bim[B.SPAN_52 - BASE] == 0, 'loader span byte +52 not 0 -> 1')
        check(im[B.SPAN_52 - 64 - BASE] == 0, 'loader lo byte +52 is not 0')
        print(f'L: span[52] ({B.SPAN_52:#x}) = {im[B.SPAN_52 - BASE]}, lo[52] ({B.SPAN_52 - 64:#x}) = {im[B.SPAN_52 - 64 - BASE]}: +52 in {{0,1}} accepted')
    sdiff = [BASE + i for i in diff if not (B.AT <= BASE + i < B.AT + len(code)) and not any(BASE + i in range(s, s + 5) for s in sites)]
    other = sorted(hex(x) for x in sdiff if x != B.SPAN_52 and not any(int(e["addr"], 16) <= x < int(e["addr"], 16) + len(e["new"]) // 2 for e in fvs))
    print(f'D: {len(diff)} bytes differ from the {"STOCK" if stock_base else "base"}; outside the stub and the site operands: {other}'
          + ('' if stock_base else f' + loader span {B.SPAN_52:#x} + fw_version label'))
    # ---- M
    n = model(spec, meta['sites'])
    print(f'M: {n} model runs (keys x idx x getter d1 behaviour x selector x mode x mode-6 x flag x other selector; no option, no accessor)')
    print('PASS' if not FAILS else f'{len(FAILS)} FAILURES')
    sys.exit(1 if FAILS else 0)


if __name__ == '__main__':
    main()
