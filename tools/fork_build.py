#!/usr/bin/env python3
"""Build a card folder from a base release plus extra patch edits, with checks. OFFLINE except `stock`.

  python3 tools/fork_build.py stock
  python3 tools/fork_build.py build --base v0.29a --patch patches/lever_nomenu/edits.json --out out/lever

`build` layers the extra edits on top of the base release (releases/<base>/edits.json), then checks:
  - the stock firmware has the official SHA-256;
  - the base release rebuilds to the exact hashes in releases/<base>/SHA256SUMS;
  - the new package differs from that base ONLY by the bytes of the extra edits;
  - the restore file is the exact stock slice (same rules as caduceus.py).
It writes <out>/DCOLYMP/E1429999.BIN, <out>/EP7MOD/ (the release's card files), <out>/restore/E1429999.BIN,
SHA256SUMS and BUILD.txt. It never touches an SD card and never flashes anything.

`--base stock` (no Caduceus release at all): the package is the official stock firmware (components 0x100 + 0x101, 0x101 untouched) + the --spec /
--patch edits, the restore file is the stock slice, there is NO EP7MOD folder. Every edit must lie inside the address ranges of a DECLARED
module (STOCK_MODULES below; `--module NAME`, repeatable; default = jpeg_always + lever_nomenu, the `minimal` package) or the build is
refused. Module ranges must not overlap each other; every declared module must be used; an edit whose `source` names another module is
refused. Edits to 0x101 are accepted only inside a declared 0x101 range (none today: 0x101 stays the stock payload).
`--expect-sha256 H` / `--expect-restore-sha256 H` pin the hashes of the patched / restore packages (nothing is written on a mismatch).
"""
import argparse, json, os, shutil, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import caduceus as C  # noqa: E402


def find_stock(explicit=None):
    cands = [Path(explicit)] if explicit else [ROOT / 'stock_firmware' / C.STOCK_NAME,
                                               ROOT / 'cache' / C.STOCK_NAME,
                                               Path.home() / 'Downloads' / C.STOCK_NAME]
    for p in cands:
        if p.is_file():
            b = p.read_bytes()
            if C.sha(b) == C.STOCK_SHA:
                return b, p
            print(f'ignored {p}: SHA-256 is not the official E-P7 1.1 file')
    return None, None


def cmd_stock(a):
    b, p = find_stock(a.stock)
    if b:
        print(f'stock firmware OK: {p}')
        return 0
    b = C.fetch_stock()
    if C.sha(b) != C.STOCK_SHA:
        raise C.Refuse('downloaded file does not have the official SHA-256; nothing saved')
    dst = ROOT / 'cache' / C.STOCK_NAME
    dst.parent.mkdir(exist_ok=True)
    dst.write_bytes(b)
    print(f'stock firmware downloaded and verified: {dst}')
    return 0


# --base stock: the only bytes a stock-based build may touch = the declared modules below.
# Ranges are (lo, hi_exclusive, why) per component: CPU addresses for 0x100, payload offsets for 0x101 (none today).
# Each range is the exact extent of the module's own build (docs/FINAL_BUILD.md); patches/final/build.py re-derives them
# from the builders and refuses if they differ from this table.
STOCK_MODULES = {
    'jpeg_always': {'0x100': [(0x601de540, 0x601de5d0, 'jo_get stub + claim'), (0x602a7f58, 0x602a7f5c, 'site 0x602a7f57 rel32'),
                              (0x602a7fec, 0x602a7ff0, 'site 0x602a7feb rel32')]},
    'lever_nomenu': {'0x100': [(0x60cd4a0a, 0x60cd4a0b, 'startProfileSelect bne -> bra')]},
    'lcd_tint': {'0x100': [(0x602355de, 0x602355de + 5850, '225-row panel table'), (0x602353ee, 0x602353ef, 'init seq G'),
                           (0x602354b2, 0x602354b3, 'init seq G'), (0x60236d2a, 0x60236d2b, 'template G')]},
    'omc_buttons': {'0x100': [(0x604cae3c, 0x604cae3c + 46, 'shared full list (23 codes)'), (0x604cda14, 0x604cda16, 'sid 47 bytes'),
                              (0x604cda20, 0x604cda24, 'sid 49 ptr'), (0x604cda28, 0x604cda2a, 'sid 49 bytes'),
                              (0x604cda34, 0x604cda38, 'sid 48 ptr'), (0x604cda3c, 0x604cda3e, 'sid 48 bytes'),
                              (0x604cdae8, 0x604cdaec, 'sid 53 ptr')]},
    'btn_arrows': {'0x100': [(0x604cb00e, 0x604cb00e + 32, 'arrow list (14 codes)'), (0x604cdadc, 0x604cdade, 'sid 51 bytes'),
                             (0x604cdaf0, 0x604cdaf2, 'sid 53 bytes'), (0x61242fe8, 0x61242ff0, 'row list'),
                             (0x61242ff0, 0x61242ff9, 'title text'), (0x6115056c, 0x61150572, 'mode-42 record'),
                             (0x611bf7c8, 0x611bf7ca, 'sid 53 item kind'), (0x611bf7cc, 0x611bf7d0, 'sid 53 item text'),
                             (0x611ccf34, 0x611ccf36, 'sid 53 item2 kind'), (0x611ccf38, 0x611ccf3c, 'sid 53 item2 text')]},
    'dial_expcomp': {'0x100': [(0x604bb480, 0x604bb481, 'M/B dial list, 2nd entry {Shutter, FNo.} -> {Shutter, Exp comp}'),
                               (0x611d6d56, 0x611d6d58, 'M/B dial page label id (second dial, value 8)'),
                               (0x6044afda, 0x6044afdb, 'rule engine sid 2, mode M group 0: sid 15210 compared with 2 (never true)')]},
    'profile_lsf': {'0x100': [(0x6043c24e, 0x6043c24f, 'quality rules result {RAW only -> JPEG slot + RAW}: slot 2 -> slot 1')]},
    'dial_iso': {'0x100': [(0x60210900, 0x6021093c, 'dial_iso stub (FNo. -> ISO on a lens without contacts, mode M)'),
                           (0x60cdc837, 0x60cdc840, 'dial routine 0x60cdc82c hook: jmp to the stub')]},
    'fw_version': {'0x100': [(0x60d7f271, 0x60d7f278, 'Firmware screen +940 setter call'), (0x60d7f2cd, 0x60d7f2d4, 'Firmware screen +300 setter call'),
                             (0x601e1c40, 0x601e1c64, 'fw_val (dead EVF step-10 B table)'), (0x6115d5e8, 0x6115d5f0, 'Body row label descriptor'),
                             (0x61242fc0, 0x61242fd0, 'label text')]},
}
DEFAULT_STOCK_MODULES = ['jpeg_always', 'lever_nomenu']      # = `make minimal`


def module_ranges(names):
    """-> sorted [(component, lo, hi, module, why)] for the declared modules; refuses unknown names, duplicates and overlaps."""
    if len(set(names)) != len(names):
        raise C.Refuse('--base stock: a module is declared twice')
    out = []
    for n in names:
        if n not in STOCK_MODULES:
            raise C.Refuse(f'--base stock: module {n!r} is not declared in STOCK_MODULES ({", ".join(STOCK_MODULES)})')
        out += [(k, lo, hi, n, why) for k, rs in STOCK_MODULES[n].items() for lo, hi, why in rs]
    out.sort()
    for x, y in zip(out, out[1:]):
        if x[0] == y[0] and y[1] < x[2]:
            raise C.Refuse(f'--base stock: ranges of modules {x[3]} and {y[3]} overlap: {x[1]:#x}-{x[2]:#x} / {y[1]:#x}-{y[2]:#x}')
    return out


def check_stock_perimeter(edits, modules=None):
    names = list(modules or DEFAULT_STOCK_MODULES)
    rng = module_ranges(names)
    used = set()
    for e in edits:
        if e['kind'] not in ('0x100', '0x101'):
            raise C.Refuse(f'--base stock: edit {e["addr"]} ({e["kind"]}) is not a main or OSD edit')
        if e['kind'] == '0x100':
            if e['addr'].startswith('off:'):
                raise C.Refuse(f'--base stock: edit {e["addr"]} (0x100) must use a CPU address')
            a = int(e['addr'], 16)
        else:
            if not e['addr'].startswith('off:'):
                raise C.Refuse(f'--base stock: edit {e["addr"]} (0x101) must use an off: payload offset')
            a = int(e['addr'][4:], 16)
        n = len(e['new']) // 2
        hit = [r for r in rng if r[0] == e['kind'] and r[1] <= a and a + n <= r[2]]
        if not hit:
            raise C.Refuse(f'--base stock: edit {e["addr"]} ({e["kind"]}, +{n}) is outside the declared modules ({", ".join(names)}): '
                           + ', '.join(f'{r[3]} {r[1]:#x}-{r[2]:#x}' for r in rng))
        src = e.get('source')
        if src and src.startswith('patches/') and src[8:] in STOCK_MODULES and src[8:] != hit[0][3]:
            raise C.Refuse(f'--base stock: edit {e["addr"]} claims source {src} but lies in module {hit[0][3]}')
        used.add(hit[0][3])
    unused = [n for n in names if n not in used]
    if unused:
        raise C.Refuse(f'--base stock: declared module(s) with no edit: {", ".join(unused)}')


def load_base(name):
    """-> (spec, published sums or None, card files). 'stock' = the official firmware, components 0x100 + 0x101 (0x101 re-written as stock, never edited), no card files."""
    if name == 'stock':
        return {'components': ['0x100', '0x101'], 'edits': []}, None, {}
    return C.load_release(name)


def payload_diff(x, y):
    """Number of differing payload bytes between two decoded packages, per component."""
    bx, by = C.parse(x), C.parse(y)
    if [C.kind(b[1]) for b in bx] != [C.kind(b[1]) for b in by]:
        raise C.Refuse('internal: component lists differ')
    n = 0
    for (_, _, p, _), (_, _, q, _) in zip(bx, by):
        if len(p) != len(q):
            raise C.Refuse('internal: payload length changed')
        n += sum(i != j for i, j in zip(p, q))
    return n


def cmd_build(a):
    out = Path(a.out)
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise C.Refuse(f'{out} already exists and is not empty; remove it or choose another --out.')
    stock, stock_path = find_stock(a.stock)
    if not stock:
        raise C.Refuse('official stock firmware not found; run: make stock')
    spec, sums, card = load_base(a.base)
    if a.spec:
        # a full edits.json built ON TOP of the base release (it may alter one of the base's own edits)
        full = json.loads(Path(a.spec).read_text())
        if full['components'] != spec['components']:
            raise C.Refuse(f'{a.spec}: component list differs from release {a.base}')
        for pth in a.patch:   # more edits on top of the full spec (apply_edits refuses overlaps)
            full['edits'] = list(full['edits']) + json.loads(Path(pth).read_text())['edits']
        return _write(a, out, stock, spec, sums, card, full=full)
    extra = []
    for pth in a.patch:
        s = json.loads(Path(pth).read_text())
        if not set(s['components']) <= set(spec['components']):
            raise C.Refuse(f'{pth}: needs components not in release {a.base}')
        extra += s['edits']
    if not extra:
        raise C.Refuse('no --patch given')
    return _write(a, out, stock, spec, sums, card, extra=extra)


def _write(a, out, stock, spec, sums, card, extra=None, full=None):
    # 1. the base release must rebuild exactly
    base_patched, base_restore = C.apply_edits(spec, stock)
    if sums is None:            # --base stock: no edits, so the "patched" base must equal the stock slice
        if base_patched != base_restore:
            raise C.Refuse('internal: the stock base slice differs from its restore')
        print('base stock: official stock firmware (components 0x100 + 0x101, 0x101 untouched), no Caduceus release, no card files')
    else:
        for n, d in (('patched.pkg.bin', base_patched), ('restore-stock.pkg.bin', base_restore)):
            if C.sha(d) != sums[n]:
                raise C.Refuse(f'base release {a.base} does not rebuild to its published hash ({n}); nothing written.')
        print(f'base release {a.base}: rebuilds to its published hashes')
    # 2. layer the extra edits (apply_edits refuses overlaps and wrong expected bytes)
    if full is None:
        full = dict(spec, edits=list(spec['edits']) + extra)
    if sums is None:
        declared = list(a.module) or list(full.get('modules') or DEFAULT_STOCK_MODULES)
        if a.module and full.get('modules') and list(full['modules']) != list(a.module):
            raise C.Refuse(f'--module {a.module} differs from the modules declared in the spec {full["modules"]}')
        check_stock_perimeter(full['edits'], declared)
        print('modules (declared, ranges disjoint, every edit inside one, every module used): ' + ', '.join(declared))
    patched, restore = C.apply_edits(full, stock)
    if restore != base_restore:
        raise C.Refuse('internal: restore file differs from the base release restore')
    got = payload_diff(base_patched, patched)
    if extra is not None:
        want = sum(x != y for e in extra for x, y in zip(bytes.fromhex(e['expect']), bytes.fromhex(e['new'])))
        if got != want:
            raise C.Refuse(f'new package differs from {a.base} by {got} bytes, expected {want}; nothing written.')
        print(f'new package differs from {a.base} by exactly {got} byte(s): {len(extra)} extra edit(s)')
        for e in extra:
            print(f'  {e["addr"]}  {e["expect"]} -> {e["new"]}   {e.get("why", "")[:90]}')
    else:
        print(f'new package differs from {a.base} by {got} byte(s) (full spec {a.spec}).'
              ' Run the patch\'s own verify.py: this script cannot tell which of these bytes are intended.')
        extra = full['edits']
    for name, got_h, want in (('patched', C.sha(patched), a.expect_sha256), ('restore', C.sha(restore), a.expect_restore_sha256)):
        if want and got_h != want:
            raise C.Refuse(f'{name} package SHA-256 {got_h} differs from the pinned {want}; nothing written.')
    files = {C.OUTPUTS['patched.pkg.bin']: patched, C.OUTPUTS['restore-stock.pkg.bin']: restore}
    files.update(card)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix='.fork-', dir=out.parent))
    try:
        for rel, data in files.items():
            f = tmp / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(data)
        (tmp / 'SHA256SUMS').write_text(''.join(f'{C.sha(d)}  {r}\n' for r, d in sorted(files.items())))
        (tmp / 'BUILD.txt').write_text(
            f'base release: {a.base}\nextra patches: {", ".join(a.patch)}\nstock: {C.STOCK_NAME} ({C.STOCK_SHA})\n'
            f'extra edits: {len(extra)}, differing bytes vs base: {got}\n'
            + ('stock-based: NO EP7MOD folder, no card file of ours is needed or used.\n' if sums is None else '') +
            'NOT tested in the emulator or on a camera unless noted elsewhere. Read docs/INSTALL.md first.\n')
        if out.exists():
            out.rmdir()
        os.replace(tmp, out)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    print(f'\nwritten to {out}:')
    for r in sorted(files):
        print(f'  {r}')
    print('\nNothing was flashed and no card was touched. Before flashing: restore file ready and tried, full battery,'
          '\none change per flash (docs/INSTALL.md). Copy DCOLYMP/ to the card; keep restore/ on your computer.')
    if sums is not None:
        print('Do NOT overwrite an existing EP7MOD/BUNDLES.BIN on the card: it holds your saved looks. Copy the other'
              '\nEP7MOD files only if they are missing.')
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog='fork_build.py', description=__doc__.split('\n\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('stock', help='check (or download and verify) the official stock firmware')
    s.add_argument('--stock')
    s.set_defaults(fn=cmd_stock)
    b = sub.add_parser('build', help='base release + extra patches -> card folder')
    b.add_argument('--base', required=True)
    b.add_argument('--patch', action='append', default=[], help='edits.json to layer (repeatable)')
    b.add_argument('--spec', help='a full edits.json built on top of the base release (instead of --patch)')
    b.add_argument('--out', required=True)
    b.add_argument('--module', action='append', default=[],
                   help='--base stock: a declared module (repeatable; default jpeg_always + lever_nomenu)')
    b.add_argument('--expect-sha256', help='pinned SHA-256 of the patched package')
    b.add_argument('--expect-restore-sha256', help='pinned SHA-256 of the restore package')
    b.add_argument('--stock')
    b.set_defaults(fn=cmd_build)
    a = ap.parse_args(argv)
    try:
        return a.fn(a)
    except C.Refuse as e:
        print(f'refused: {e}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
