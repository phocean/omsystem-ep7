#!/usr/bin/env python3
"""FINAL spec = stock 1.1 + jpeg_always + lever_nomenu + lcd_tint + more button functions (omc_buttons + btn_arrows) + fw_version
(Setup > Firmware, Body row: title "phocean", value "1.0"; display only). Offline.

  python3 -I patches/final/build.py --jpeg generated/jpeg_always_stock/edits.json --out generated/final/edits.json
          [--without lcd_tint|omc_buttons|btn_arrows|fw_version] [--label phocean] [--version 1.0]    # same spec minus one module (the base the module verifiers diff against)

Nothing here depends on Caduceus v0.29a: every module is rebuilt from the STOCK image (analysis/ep7_1100/...decoded.bin,
EP7_STOCK_MAIN overrides) with its own builder code:
  jpeg_always   patches/jpeg_always/build.py --base stock (input: --jpeg) + patches/lever_nomenu/edits.json
  lcd_tint      patches/lcd_tint/build.py edits(8 %, 16 %)            (pure data, 4 edits)
  omc_buttons   patches/buttons/build.py edits(): shared 23-code list for sids 47/48/49 + their record fields + sid 53 ptr
  btn_arrows    patches/btn_arrows/build.py apply(version=None): arrow list 14 codes, rows [47, 48, 53, 51], "Right Fn"
The omc_buttons / btn_arrows `apply()` entry points need a v0.28 base and the fw_version label; here we call the same
helpers on the stock image with version=None (no Caduceus label); the fork's own label comes from patches/fw_version (code 0x601e1c40, text 0x61242fc0).
Checks (refuses on any failure):
  * every module edit has the stock bytes as `expect` (caduceus.apply_edits re-checks), no two edits overlap;
  * the ranges derived from the edits are inside the ranges declared for the module in tools/fork_build.py STOCK_MODULES,
    and every declared range of lcd_tint / omc_buttons / btn_arrows is exactly an edit;
  * if releases/v0.29a/edits.json exists: the lcd_tint / omc_buttons / btn_arrows edits are byte-identical to the ones of v0.29a
    (same address, same new bytes, same expect), so the behaviour tested in v0.29a is the one built here;
  * the stock preconditions of patches/buttons static_checks, and the sec-6 tail used by btn_arrows is FF in the stock.
"""
import argparse, importlib.util, json, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))


def load(name, rel):
    s = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


LT = load('final_lcd_tint', 'patches/lcd_tint/build.py')
BT = load('final_buttons', 'patches/buttons/build.py')
BA = load('final_btn_arrows', 'patches/btn_arrows/build.py')
FW = load('final_fw_version', 'patches/fw_version/build.py')
import fork_build as FB  # noqa: E402

MODULES = ['jpeg_always', 'lever_nomenu', 'lcd_tint', 'omc_buttons', 'btn_arrows', 'fw_version']
LABEL, VERSION = 'phocean', '1.0'     # Setup > Firmware, Body row: title and value (display only; the box is narrow, keep both short)
B = 0x60020020


def die(msg):
    raise SystemExit(f'final/build.py refused: {msg}')


def stock_image():
    p = Path(os.environ.get('EP7_STOCK_MAIN') or ROOT / 'analysis/ep7_1100/00_0100_406a0020.decoded.bin')
    d = p.read_bytes()
    if len(d) != 26214336:
        die(f'{p}: not the 0x100 payload')
    return d


def omc_edits(stock):
    bad = [n for n, ok, _ in BT.static_checks(stock) if not ok]
    if bad:
        die(f'stock preconditions of patches/buttons fail: {bad}')
    return [dict(e, source='patches/omc_buttons') for e in BT.edits(stock)]


def build(jpeg_spec, stock, label=LABEL, version=VERSION):
    edits = []
    for e in jpeg_spec['edits']:
        if e['kind'] != '0x100' or e.get('source') != 'patches/jpeg_always':
            die(f'jpeg_always spec: unexpected edit {e["addr"]} ({e["kind"]}, {e.get("source")})')
        edits.append(dict(e))
    if jpeg_spec.get('jpeg_always', {}).get('base') != 'stock':
        die('--jpeg is not the --base stock build of jpeg_always')
    lever = json.loads((ROOT / 'patches/lever_nomenu/edits.json').read_text())
    edits += [dict(e, source='patches/lever_nomenu') for e in lever['edits']]
    edits += LT.edits(LT.DEFAULT_PCT, LT.DEFAULT_SPAN, stock)
    pseudo = {'edits': omc_edits(stock), 'buttons': BT.spec()['buttons']}
    pseudo = BA.apply(pseudo, version=None)           # converts the arrow part to btn_arrows, adds rows / record / title
    edits += pseudo['edits']
    fw = FW.apply({'edits': []}, version, label)      # label + value on the Firmware screen (display only)
    edits += fw['edits']
    spec = {'components': ['0x100', '0x101'], 'modules': list(MODULES), 'edits': edits,
            'buttons': pseudo['buttons'], 'omc_buttons': {'built_by': 'patches/final (stock image, no fw_version)'},
            'btn_arrows': pseudo['btn_arrows'], 'fw_version': fw['fw_version'], 'jpeg_always': jpeg_spec['jpeg_always'],
            'lcd_tint': {'green_pct': LT.DEFAULT_PCT, 'span_pct': LT.DEFAULT_SPAN, 'table': hex(LT.TABLE), 'rows': LT.ROWS}}
    return spec


def module_of(e):
    s = e.get('source', '')
    if not s.startswith('patches/') or s[8:] not in MODULES:
        die(f'edit {e["addr"]} has no module source ({s!r})')
    return s[8:]


def checks(spec, stock):
    edits = spec['edits']
    # overlaps and stock bytes
    spans = []
    for e in edits:
        a, n = int(e['addr'], 16), len(e['new']) // 2
        if stock[a - B:a - B + n].hex() != e['expect']:
            die(f'{e["addr"]}: expect is not the stock bytes')
        if any(a < y and x < a + n for x, y in spans):
            die(f'{e["addr"]}: overlaps another edit')
        spans.append((a, a + n))
    # derived ranges inside the declared ones; declared ranges of the data modules are exactly edits
    for m in MODULES:
        mine = [(int(e['addr'], 16), int(e['addr'], 16) + len(e['new']) // 2) for e in edits if module_of(e) == m]
        decl = [(lo, hi) for lo, hi, _ in FB.STOCK_MODULES[m]['0x100']]
        if not mine:
            die(f'module {m}: no edit')
        for lo, hi in mine:
            if not any(dl <= lo and hi <= dh for dl, dh in decl):
                die(f'module {m}: edit {lo:#x}-{hi:#x} is outside the ranges declared in fork_build.STOCK_MODULES')
        if m in ('lcd_tint', 'omc_buttons', 'btn_arrows') and sorted(mine) != sorted(decl):
            die(f'module {m}: derived ranges differ from fork_build.STOCK_MODULES: {sorted(mine)} / {sorted(decl)}')
    # sec-6 tail (btn_arrows rows + title) is FF in stock and inside the section load (end 0x61243000)
    if set(stock[0x61242fe0 - B:0x61243000 - B]) != {0xff}:
        die('sec-6 tail 0x61242fe0-0x61243000 is not FF in the stock')
    # same bytes as v0.29a
    rel = ROOT / 'releases/v0.29a/edits.json'
    if rel.is_file():
        r = json.loads(rel.read_text())
        for m in ('lcd_tint', 'omc_buttons', 'btn_arrows'):
            want = sorted((e['addr'], e['expect'], e['new']) for e in r['edits'] if e.get('source') == f'patches/{m}')
            got = sorted((e['addr'], e['expect'], e['new']) for e in edits if module_of(e) == m)
            if want != got:
                die(f'module {m}: differs from the v0.29a edits ({len(want)} vs {len(got)})')
        print('final == v0.29a for lcd_tint (4 edits), omc_buttons (7), btn_arrows (10): same address, expect and new bytes')
    else:
        print('releases/v0.29a/edits.json absent: v0.29a equality not checked')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--jpeg', type=Path, required=True, help='jpeg_always --base stock edits (patches/jpeg_always/build.py)')
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--without', choices=MODULES, help='drop one module (verifier base)')
    ap.add_argument('--label', default=LABEL)
    ap.add_argument('--version', default=VERSION)
    a = ap.parse_args()
    stock = stock_image()
    spec = build(json.loads(a.jpeg.read_text()), stock, a.label, a.version)
    checks(spec, stock)
    if a.without:
        spec['edits'] = [e for e in spec['edits'] if module_of(e) != a.without]
        spec['modules'] = [m for m in spec['modules'] if m != a.without]
        if a.without == 'fw_version':
            spec.pop('fw_version', None)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(spec, indent=1) + '\n')
    per = {m: (sum(module_of(e) == m for e in spec['edits']), sum(len(e['new']) // 2 for e in spec['edits'] if module_of(e) == m))
           for m in spec['modules']}
    print(f'wrote {a.out}: {len(spec["edits"])} edits; module -> (edits, bytes) {per}')


if __name__ == '__main__':
    main()
