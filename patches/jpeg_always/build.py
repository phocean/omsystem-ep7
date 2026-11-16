#!/usr/bin/env python3
"""JPEG always on COLOR / MONO profiles (definitive, no option, no SD read). Offline. docs/JPEG_ALWAYS.md.

  # layered on the v0.29a release (the way patches/sharp_off is):
  python3 -I patches/jpeg_always/build.py releases/v0.29a/edits.json --out generated/jpeg_always/edits.json

  default: ONLY the two capture-record sites (0x602a7f57, 0x602a7feb) are redirected.
  options: --version 0.29j     Firmware screen label (patches/fw_version, 5 characters: the value box is narrow); '' leaves the base's
           --msg               ALSO redirect the two settings-message reads (0x60554e76 / 0x60554e87).
                               WARNING: high risk, not proven. The consumer of message byte +62 is not identified.
           --estimator         ALSO redirect the view-count estimator read 0x6061e079. WARNING: same, and the other
                               estimators still count RAW.
           --stock-main PATH   decoded stock main (default analysis/ep7_1100/00_0100_406a0020.decoded.bin, or $EP7_STOCK_MAIN)

What it does (the capture code is 0x602a7f2d..0x602a7f71 and 0x602a7fb5..0x602a800e): the capture record's file type
(+23920 slot 1, +23922 slot 2) is 5 (JPEG + RAW) when the "RAW in addition" flag (key 0x8231 / 0x5141) reads 1, else 0 (JPEG).
`jo_get` (jo.s.in) answers 0 for that flag when the picture mode is COLOR or MONO and the quality selector is not 3 / 4. Always.
There is NO option byte and no read of the card: the stub never calls the SD accessor tbl_off.
MIGRATION: the SD loader's per-byte range for +52 STAYS 0..1 (0x605b7755 = 1, the same edit as patches/jpeg_only), so a BUNDLES.BIN
written for jpeg_only (+52 = 1) is still accepted whole. The value is ignored by this firmware.

Checks (each raises, nothing is written): stock bytes and getter targets of every site, key/a0/d1 setup before each call,
no branch into a site's operand bytes, claim range inside the dead EVF gamma table 0x601de53c with only its step-table word
as reference, no overlap with any edit of the base, the base has the v3 loader spans (+50, +51) and span +52 = 0, section load
order, forbidden opcodes (mul/div/setlb/lxx/trap, fb forms), no stores, no call to the SD accessor, alignment.
"""
import argparse, copy, importlib.util, json, os, re, struct, subprocess, sys, tempfile
from array import array
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
BASE, SRC = 0x60020020, 'patches/jpeg_always'
STOCK = Path(os.environ.get('EP7_STOCK_MAIN') or ROOT / 'analysis/ep7_1100/00_0100_406a0020.decoded.bin')


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


SB3 = _load('ep7_sd_bundles_v3_build', ROOT / 'patches/sd_bundles_v3/build.py')   # assemble / disasm / store_audit / accessor
TC = SB3.TC

GETTER = 0x6005e971
TBL_OFF = 0x6055e7b6                      # v3 accessor: NOT used any more; only checked that the stub never calls it
AT, END = 0x601de540, 0x601de5d0          # claim (144 B). Inside the dead EVF gamma table 0x601de53c..0x601de63c (step-table word 0x601e3c14)
TBL_START, TBL_END, TBL_REF = 0x601de53c, 0x601de63c, {0x601e3c14: 0x601de53c}
LOADER_BYTE = 52                          # slot byte 52: no option any more; its loader span stays 0..1 (migration from jpeg_only)
RANGE = 0x605b7721                        # SD loader v3 per-byte span table (slot byte n at +n); lo table at RANGE - 64
SPAN_52 = RANGE + LOADER_BYTE

# key = id << 4 | type, type 1 = unsigned byte
K_FLAG1, K_FLAG2 = 0x8231, 0x5141         # "RAW in addition" flag, slot 1 (sid 22) / slot 2 (sid 1105)
K_SEL1, K_SEL2 = 0x8141, 0x5131           # quality selector, slot 1 (sid 10) / slot 2 (sid 1104)
K_PMODE, K_PMODE6 = 0x9481, 0x9d11        # picture mode (sid 111); 6 is re-resolved through 0x9d11 as the capture does (0x602a856e)

# site, key, group, role, key-load address, a0 = 0 address (90 00), clr d1 address (04)
SITES = [
    (0x602a7f57, K_FLAG1, 'capture', 'capture record +23920 (slot 1 file type)', 0x602a7f4e, 0x602a7f54, 0x602a7f56),
    (0x602a7feb, K_FLAG2, 'capture', 'capture record +23922 (slot 2 file type)', 0x602a7fe5, 0x602a7fe8, 0x602a7fea),
    (0x60554e76, K_FLAG1, 'msg', 'settings message +62 (RAW flag), slot 1', 0x60554e70, 0x60554e6b, 0x60554e48),
    (0x60554e87, K_FLAG2, 'msg', 'settings message +62 (RAW flag), slot 2', 0x60554e81, 0x60554e84, 0x60554e86),
    (0x6061e079, K_FLAG1, 'est', 'view-count estimator (size class 6 = JPEG + RAW)', 0x6061e070, 0x6061e076, 0x6061e078),
]
# the nine sections {start, end}, load order 1, 7, 2, 3, 4, 5, 6, 8, 9 (docs/FIRMWARE_GUIDE.md section 2)
SECTIONS = {1: (0x600d7800, 0x60211000), 2: (0x60280800, 0x6055e800), 3: (0x6057b200, 0x605b7800), 4: (0x605baa00, 0x60748000),
            5: (0x6075a800, 0x60b9e000), 6: (0x60ba7000, 0x61243000), 7: (0x612c7000, 0x61379000), 9: (0x613c1000, 0x6143a800)}
LOAD_ORDER = [1, 7, 2, 3, 4, 5, 6, 8, 9]
BAD = {'mul', 'mulu', 'div', 'divu', 'setlb', 'llt', 'lne', 'leq', 'lra', 'lcc', 'lcs', 'trap'}


def s16(k):
    if not 0 < k < 0x10000 or k & 0xf != 1:
        raise SystemExit(f'key {k:#x}: not a 16-bit type-1 (u8) key')
    return k - 0x10000 if k & 0x8000 else k


def section(addr):
    for k, (lo, hi) in SECTIONS.items():
        if lo <= addr < hi:
            return k
    return None


def rel(at, dst):
    return struct.pack('<i', dst - at)


def img_of(spec, stock):
    im = bytearray(stock)
    for e in spec['edits']:
        if e['kind'] == '0x100' and not e['addr'].startswith('off:'):
            a = int(e['addr'], 16) - BASE
            n = bytes.fromhex(e['new'])
            im[a:a + len(n)] = n
    return bytes(im)


def put(spec, stock, addr, old, new, why):
    """Into the edit that covers addr (build_package refuses overlapping edits), else a new edit. old = the bytes there now."""
    im = img_of(spec, stock)
    if im[addr - BASE:addr - BASE + len(old)] != old:
        raise SystemExit(f'{addr:#x}: {im[addr - BASE:addr - BASE + len(old)].hex()} != {old.hex()} ({why})')
    for e in spec['edits']:
        if e['kind'] == '0x100' and not e['addr'].startswith('off:'):
            a, n = int(e['addr'], 16), len(e['new']) // 2
            if a <= addr and addr + len(new) <= a + n:
                b = bytearray.fromhex(e['new'])
                b[addr - a:addr - a + len(new)] = new
                e['new'] = b.hex()
                e['why'] += f' [jpeg_always: {why}]'
                return
            if a < addr + len(new) and addr < a + n:
                raise SystemExit(f'{addr:#x}: straddles edit {e["addr"]}')
    spec['edits'].append(dict(kind='0x100', addr=hex(addr), expect=stock[addr - BASE:addr - BASE + len(new)].hex(), new=new.hex(), source=SRC,
                              why=f'jpeg_always {why}'))


def abs32_hits(img, lo, hi):
    """abs32 words (any byte offset, cached and uncached alias) with a value in [lo, hi)."""
    out = []
    for off in range(4):
        n = (len(img) - off) // 4
        w = array('I')
        w.frombytes(img[off:off + n * 4])
        for k, v in enumerate(w):
            if lo <= v < hi or lo + 0x40000000 <= v < hi + 0x40000000:
                out.append((BASE + off + 4 * k, v))
    return sorted(out)


def rel32_hits(img, lo, hi):
    """jmp d32 (0xdc) / call d32 (0xdd) encodings at any byte offset whose target is in [lo, hi)."""
    out = []
    for op in (b'\xdc', b'\xdd'):
        i = img.find(op)
        while i != -1:
            if i + 5 <= len(img):
                t = BASE + i + struct.unpack_from('<i', img, i + 1)[0]
                if lo <= t < hi:
                    out.append((BASE + i, t))
            i = img.find(op, i + 1)
    return out


def check_site(stock, site, key, load_at, a0_at, d1_at):
    o = site - BASE
    if stock[o] != 0xdd or site + struct.unpack_from('<i', stock, o + 1)[0] != GETTER or stock[o + 5:o + 7] != b'\xc0\x0c':
        raise SystemExit(f'site {site:#x}: not `call {GETTER:#x},[d2,d3],12`: {stock[o:o + 7].hex()}')
    ld = bytes([0xfc, 0xcc]) + struct.pack('<I', key) if key & 0x8000 else bytes([0x2c]) + struct.pack('<H', key)
    if stock[load_at - BASE:load_at - BASE + len(ld)] != ld:
        raise SystemExit(f'site {site:#x}: key {key:#x} load not at {load_at:#x}')
    if stock[a0_at - BASE:a0_at - BASE + 2] != b'\x90\x00' or stock[d1_at - BASE] != 0x04:
        raise SystemExit(f'site {site:#x}: `mov 0,a0` / `clr d1` not at {a0_at:#x} / {d1_at:#x}')
    # nothing between those and the call writes a0 / d1 (best effort on the disassembly; the instruction list is in the report)
    for start, reg in ((a0_at + 2, 'a0'), (d1_at + 1, 'd1')):
        if start >= site:
            continue
        for a, op, args in SB3.disasm(stock[start - BASE:site - BASE], start, site):
            dest = args.split(',')[-1].strip() if args else ''
            if op in ('call', 'calls', 'jmp', 'bsr') or dest == reg or (op in ('clr', 'inc', 'extb', 'extbu', 'exth', 'exthu') and args.strip() == reg):
                if not (op == 'mov' and dest == 'd0'):
                    raise SystemExit(f'site {site:#x}: {a:#x} `{op} {args}` between the {reg} setup and the call')
    # nothing branches into the call's operand bytes
    hits = rel32_hits(stock, site + 1, site + 7)
    if hits:
        raise SystemExit(f'site {site:#x}: jmp / call d32 into its operand bytes: {[(hex(a), hex(t)) for a, t in hits]}')


def source():
    sub = dict(key_flag1=s16(K_FLAG1), key_flag2=s16(K_FLAG2), key_sel1=s16(K_SEL1), key_sel2=s16(K_SEL2), k_pmode=s16(K_PMODE),
               k_pmode6=s16(K_PMODE6))
    return SB3.subst((HERE / 'jo.s.in').read_text(), sub)


def data_alignment(src, syms):
    bad, label = [], None
    for line in src.splitlines():
        m = re.match(r'^(\w+):', line)
        if m:
            label = m.group(1)
            continue
        d = line.split('/*')[0].strip()
        if label and d:
            need = 4 if d.startswith(('.long', '.word')) else 2 if d.startswith(('.hword', '.short')) else 0
            if need and syms.get(label, 0) % need:
                bad.append((label, hex(syms[label])))
            label = None
    return bad


def build_code(stock):
    src = source()
    code, lst, s, dis = SB3.assemble(src, AT, dict(ep7_getter=GETTER))
    if s['jo_get'] != AT or AT % 4:
        raise SystemExit('jo_get must be the first instruction on a 4-byte boundary')
    if AT + len(code) > END:
        raise SystemExit(f'{len(code)} B does not fit the claim {AT:#x}..{END:#x}')
    ins = SB3.disasm(code, AT, AT + len(code))
    if not ins or ins[0][0] != AT:
        raise SystemExit('disassembly does not start at jo_get')
    if any(op in BAD for _, op, _ in ins):
        raise SystemExit('forbidden instruction: ' + ', '.join(f'{a:#x} {op}' for a, op, _ in ins if op in BAD))
    if any(code[a - AT] == 0xfb for a, _, _ in ins):
        raise SystemExit('fb-prefixed instruction form')
    stores = SB3.store_audit(ins)
    if stores:
        raise SystemExit(f'the stub must not store: {stores}')
    if data_alignment(src, s):
        raise SystemExit(f'misaligned data: {data_alignment(src, s)}')
    # the instruction stream must cover the code exactly (no data in this stub)
    end = ins[-1][0]
    if not code or any(a >= AT + len(code) for a, _, _ in ins):
        raise SystemExit('disassembly overruns the code')
    # the stub must not call anything but the stock getter (no SD accessor, no table)
    bad = [(hex(a), op, args) for a, op, args in ins if op in ('call', 'jmp') and int(args.split(',')[0], 0) != GETTER
           and not (AT <= int(args.split(',')[0], 0) < AT + len(code))]
    if bad or any(f'{TBL_OFF:#x}' in args for _, _, args in ins):
        raise SystemExit(f'the stub must only call the stock getter {GETTER:#x}: {bad}')
    if any(op == 'movbu' or op.startswith('mov') and '(' in args for _, op, args in ins):
        raise SystemExit('the stub must not read memory')
    return code, lst, s, ins, dis


def check_range_free(spec, stock):
    if not (TBL_START <= AT and END <= TBL_END):
        raise SystemExit('claim is outside the dead EVF gamma table')
    for e in spec['edits']:
        if not e['addr'].startswith('off:'):
            a, n = int(e['addr'], 16), len(e['new']) // 2
            if a < END and AT < a + n:
                raise SystemExit(f'overlap with edit {e["addr"]}')
    # stock bytes of the table: a gamma ramp (value = index), nothing else lives here
    if any(stock[TBL_START - BASE + i] != i for i in range(256)):
        raise SystemExit('0x601de53c.. is not the identity gamma ramp any more')
    hits = abs32_hits(stock, TBL_START, TBL_END)
    extra = [(hex(a), hex(v)) for a, v in hits if TBL_REF.get(a) != v]
    if extra or {a for a, _ in hits} != set(TBL_REF):
        raise SystemExit(f'references into {TBL_START:#x}..{TBL_END:#x}: {extra or "step-table word missing"}')
    rel = [(hex(a), hex(t)) for a, t in rel32_hits(stock, TBL_START, TBL_END)]
    if rel:
        raise SystemExit(f'jmp / call d32 into the table: {rel}')
    return hits


def check_sections():
    rank = {k: LOAD_ORDER.index(k) for k in SECTIONS}
    stub = section(AT)
    if stub != 1:
        raise SystemExit('stub must sit in section 1')
    out = {}
    for site, *_ in SITES:
        sec = section(site)
        if sec is None or rank[sec] <= rank[stub]:
            raise SystemExit(f'site {site:#x} (section {sec}) is not loaded after the stub (section {stub})')
        out[hex(site)] = sec
    return dict(stub=stub, sites=out)


def check_base(spec, stock, im):
    """The base must be a v0.29-line image with the v3 loader; the span of +52 is 0 there and the stub does not read it."""
    if im[SPAN_52 - BASE] != 0 or im[SPAN_52 - 64 - BASE] != 0:
        raise SystemExit('loader span/lo for +52 is not 0/0 in the base')
    if im[RANGE + 51 - BASE] != 1 or im[RANGE + 50 - BASE] != 3:
        raise SystemExit('the base loader does not have the v0.28 spans (+50 grain 0..3, +51 sharp 0..1)')
    # the loader span table region is part of one edit (put() will modify it)
    cov = [e for e in spec['edits'] if not e['addr'].startswith('off:') and int(e['addr'], 16) <= SPAN_52 < int(e['addr'], 16) + len(e['new']) // 2]
    if len(cov) != 1:
        raise SystemExit(f'{SPAN_52:#x} is in {len(cov)} edits')


def apply(spec, version='0.29j', msg=False, estimator=False, stock_base=False):
    """stock_base: spec is the empty stock spec; no loader edit, no version label, nothing from any release is needed."""
    stock = STOCK.read_bytes()
    spec = copy.deepcopy(spec)
    if version and not stock_base:
        FV = _load('fw_version_build', ROOT / 'patches/fw_version/build.py')
        FV.STOCK = STOCK
        spec = FV.apply(spec, version)
    im = img_of(spec, stock)
    sec_info = check_sections()
    check_range_free(spec, stock)
    if stock_base:
        if spec['edits'] or im != stock:
            raise SystemExit('stock base: the base spec must have no edits')
    else:
        check_base(spec, stock, im)
    chosen = [s for s in SITES if s[2] == 'capture' or (s[2] == 'msg' and msg) or (s[2] == 'est' and estimator)]
    # no existing edit may touch a chosen site's operand bytes
    for site, key, grp, role, load_at, a0_at, d1_at in chosen:
        check_site(stock, site, key, load_at, a0_at, d1_at)
        if im[site - BASE:site - BASE + 7] != stock[site - BASE:site - BASE + 7]:
            raise SystemExit(f'site {site:#x} is already edited in the base')
    code, lst, s, ins, dis = build_code(stock)
    spec['edits'].append(dict(kind='0x100', addr=hex(AT), expect=stock[AT - BASE:AT - BASE + len(code)].hex(), new=code.hex(), source=SRC,
                              why=f'jpeg_always: jo_get ({len(code)} B, no option, dead EVF gamma table 0x601de53c)'))
    for site, key, grp, role, *_ in chosen:
        spec['edits'].append(dict(kind='0x100', addr=hex(site + 1), expect=stock[site + 1 - BASE:site + 5 - BASE].hex(), new=rel(site, s['jo_get']).hex(),
                                  source=SRC, why=f'jpeg_always: getter call {site:#x} (key {key:#x}) rel32 -> jo_get ({role})'))
    if not stock_base:
        put(spec, stock, SPAN_52, b'\x00', b'\x01', 'SD loader v3 range: slot byte +52 stays 0..1 (accepts BUNDLES.BIN of jpeg_only; value ignored)')
    spec['jpeg_always'] = dict(built_by=SRC, version=version, code_at=hex(AT), code_len=len(code), claim_end=hex(END), option_byte=None,
                             base='stock' if stock_base else 'release', groups=dict(capture=True, msg=msg, estimator=estimator),
                             sites=[hex(c[0] + 1) for c in chosen], loader_span=None if stock_base else hex(SPAN_52), sections=sec_info,
                             symbols={k: hex(v) for k, v in s.items()},
                             keys=dict(flag1=hex(K_FLAG1), flag2=hex(K_FLAG2), sel1=hex(K_SEL1), sel2=hex(K_SEL2), pmode=hex(K_PMODE), pmode6=hex(K_PMODE6)),
                             requires='stock: nothing. v0.29a: sd_bundles_v3 loader (for the +52 migration). No accessor, no SD read; excludes patches/jpeg_only (same claim)')
    return spec, (source(), lst, dis)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('spec', nargs='?', type=Path)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--version', default='0.29j')
    ap.add_argument('--msg', action='store_true', help='WARNING high risk, not proven: also redirect the settings-message reads (+62 consumer unknown)')
    ap.add_argument('--estimator', action='store_true', help='WARNING high risk, not proven: also redirect the view-count estimator read')
    ap.add_argument('--base', default='release', choices=('release', 'stock'), help='release (default): layered on the base spec given; stock: official firmware + this patch only (no loader edit, no label)')
    ap.add_argument('--stock-main', type=Path)
    a = ap.parse_args()
    global STOCK
    if a.stock_main:
        STOCK = a.stock_main
    if a.base == 'stock':
        if a.spec:
            ap.error('--base stock takes no base spec')
        if a.version and a.version != ap.get_default('version'):
            ap.error('--base stock: no version label (patches/fw_version belongs to the v0.29a code)')
        base = {'components': ['0x100', '0x101'], 'edits': []}
        spec, (src, lst, dis) = apply(base, '', a.msg, a.estimator, True)
    else:
        if not a.spec:
            ap.error('give a base spec (releases/v0.29a/edits.json) or --base stock')
        base = json.loads(a.spec.read_text())
        if '0x100' not in base['components']:
            ap.error('base spec has no main component')
        spec, (src, lst, dis) = apply(base, a.version, a.msg, a.estimator, False)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(spec, indent=1))
    a.out.with_suffix('.lst').write_text(lst)
    m = spec['jpeg_always']
    print(f"jpeg_always {m['code_len']} B at {m['code_at']}..{int(m['code_at'], 16) + m['code_len']:#x} (claim to {m['claim_end']}); sites {m['sites']}; "
          f"loader span {m['loader_span']}; wrote {a.out}")


if __name__ == '__main__':
    main()
