#!/usr/bin/env python3
"""Checks of the FINAL package (stock + jpeg_always + lever_nomenu + lcd_tint + omc_buttons + btn_arrows). Offline, emulator only.

  PYTHONPATH=<main repo>/external/oly_fw_analysis/tools python3 patches/final/verify.py SPEC BASE_NO_OMC [--pkg out/final] [--v029a releases/v0.29a/edits.json]

  P  package: the card file is exactly tools/build_package.build(SPEC) (checksums valid, restore == stock slices, 0x101 == stock)
  D  decomposition: the bytes differing from the stock are exactly the union of the per-module builds (each module built alone on
     the stock), the modules are pairwise disjoint; per-component and per-module counts are printed
  O  the omc_buttons checks of patches/omc_buttons/verify.py (V validator, N stepping, A dispatch, Y alignment, P anti-brick) run on the
     FINAL image against BASE_NO_OMC (= final without the omc_buttons edits). The L check (version label "0.28o1") is not applicable:
     the final has no version label (fw_version is a Caduceus-only module)
  W  windows (needs --v029a): every byte the buttons / lcd / label / dispatch code and data read lies identically in the final image and
     in the v0.29a image, except the allowed list (setting 270 validator record, another feature); anything else is a hidden dependency
  C  (needs --v029a) no other v0.29a edit overlaps a range claimed by a module of the final (tools/fork_build.py STOCK_MODULES)
  X  emulator, final vs v0.29a: validator count/value/stepping of sids 47-53 and their neighbours, function -> action for every listed
     code, key kinds, and the LCD panel routine's 70-byte SPI buffer for 3 brightness x 15 colour steps are identical
Exit code 0 = everything PASS.
"""
import argparse, importlib.util, json, struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'external/oly_fw_analysis/tools')]
import build_package as BP  # noqa: E402
import oly_container as oc  # noqa: E402


def load(name, rel):
    s = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


try:        # needs numpy; it does `import build` (patches/lcd_tint), which must not stay cached for ep7_buttons_verify
    LV = load('final_lcd_verify', 'tools/ep7_verify_lcd_tint.py')
except ImportError as e:
    LV, LV_ERR = None, str(e)
sys.modules.pop('build', None)
import ep7_buttons_verify as V  # noqa: E402
OV = load('final_omc_verify', 'patches/omc_buttons/verify.py')
BT, B = V.BT, V.B
MODULES = ['jpeg_always', 'lever_nomenu', 'lcd_tint', 'omc_buttons', 'btn_arrows', 'fw_version']
# data / code the button + LCD features read (CPU addresses, end exclusive)
WINDOWS = {'validator API': (0x602b9c00, 0x602ba600), 'validator records': (0x604cc98c, 0x604cc98c + 1333 * 20),
           'button lists': (0x604cae00, 0x604cb040), 'dispatcher': (0x60cc8700, 0x60cc8c00),
           'key table': (0x60f389a8, 0x60f38af8), 'function table': (0x60f38af8, 0x60f38e00),
           'Cursor_Move code': (0x60de1f00, 0x60de3800), 'Cursor_Move mode table': (0x61150328, 0x61150328 + 150 * 12),
           'value label list (44)': (0x611baf8c, 0x611baf8c + 44 * 12), 'Button Function labels': (0x611d78cc, 0x611d7da0),
           'sid 53 item records': (0x611bf780, 0x611bf800), 'sid 53 item records 2': (0x611ccee0, 0x611ccf80),
           'row-title builders': (0x60df2500, 0x60df2640), 'value-column text': (0x60e8a000, 0x60e8b200),
           'LCD panel routine': (0x60182000, 0x60184800), 'LCD .data': (0x602352e0, 0x60236e00),
           'LCD init copy': (0x60042300, 0x60042400), 'sec-6 tail used': (0x61242fe0, 0x61243000)}
ALLOWED_DIFF = [(0x604cec18, 0x604cec22, 'setting 270 validator record (another Caduceus feature; not read by sids 47-53)'),
                (0x60df255f, 0x60df2565, 'v0.29a film-menu label builder A hook jmp (kind-4 point; stock path for every non-film row)'),
                (0x60df25dc, 0x60df25e2, 'v0.29a film-menu label builder B hook jmp (same)')]
results = []


def report(name, ok, detail=''):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f'  {detail}' if detail else ''), flush=True)


def main_payload(pkg):
    return [b for b in oc.parse(pkg) if b.kind == 0x100][0].payload


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('spec', type=Path)
    ap.add_argument('base_no_omc', type=Path)
    ap.add_argument('--pkg', type=Path)
    ap.add_argument('--v029a', type=Path)
    a = ap.parse_args()
    spec, base_s = json.loads(a.spec.read_text()), json.loads(a.base_no_omc.read_text())
    stock_file = BP.STOCK.read_bytes()
    pkg, rst, info = BP.build(spec, stock_file)
    img = main_payload(pkg)
    stock = main_payload(rst)
    sb = {b.kind: b.payload for b in oc.parse(stock_file)}

    # P
    ok = [b.kind for b in oc.parse(pkg)] == [0x100, 0x101] and [b.payload for b in oc.parse(pkg)][1] == sb[0x101]
    if a.pkg:
        ok &= (a.pkg / 'DCOLYMP/E1429999.BIN').read_bytes() == pkg and (a.pkg / 'restore/E1429999.BIN').read_bytes() == rst
    report('P package == build_package(spec); 0x101 == stock; card files match', ok,
           f'{info["edits"]} edits, {info["changed_payload_bytes"]} changed bytes; patched {BP.sha(pkg)[:16]} restore {BP.sha(rst)[:16]}')

    # D
    diff = {i for i in range(len(img)) if img[i] != stock[i]}
    per, union, disjoint = {}, set(), True
    for m in MODULES:
        ms = dict(spec, edits=[e for e in spec['edits'] if e.get('source') == f'patches/{m}'])
        mp, _, _ = BP.build(ms, stock_file)
        d = {i for i, (x, y) in enumerate(zip(main_payload(mp), stock)) if x != y}
        per[m] = len(d)
        disjoint &= not (d & union)
        union |= d
    report('D final differs from stock by exactly the union of the disjoint module builds', union == diff and disjoint,
           f'0x100: {len(diff)} bytes ({", ".join(f"{m} {n}" for m, n in per.items())}); 0x101: 0 bytes')

    # O  (omc_buttons checks on the final image)
    old = main_payload(BP.build(base_s, stock_file)[0])
    b = spec['buttons']
    S, O, P = V.Img(stock), V.Img(old), V.Img(img)
    others = OV.others_list(stock)
    ok = True
    for name, fn in (('V validator', lambda: OV.t_validator(S, O, P, b, others)),
                     ('N stepping', lambda: (lambda r: ([x for x in r[1] if not x['passed']], len(r[1])))(V.check_next(S, P, b))),
                     ('A dispatch', lambda: (lambda r: ([x for x in r[1] if not x['passed']], len(r[1])))(V.check_dispatch(S, P, b))),
                     ('Y alignment', lambda: OV.t_align(b))):
        bad, n = fn()
        ok &= not bad
        report(f'O {name}: {n - len(bad)}/{n}', not bad, str(bad[:3]) if bad else '')
    # anti-brick P of omc: only the omc sites differ from the base without omc
    ours = [(int(e['addr'], 16), len(e['new']) // 2) for e in spec['edits'] if e.get('source') == 'patches/omc_buttons']
    stray = [hex(B + i) for i in range(len(old)) if old[i] != img[i] and not any(s <= B + i < s + k for s, k in ours)]
    report('O anti-brick: only omc_buttons sites differ from final-without-omc', not stray, str(stray[:6]) if stray else '')

    if not a.v029a:
        print('W/X skipped (no --v029a)')
    else:
        # W
        v29 = main_payload(BP.build(json.loads(a.v029a.read_text()), stock_file)[0])
        bad = []
        for k, (lo, hi) in WINDOWS.items():
            for i in range(lo - B, hi - B):
                if v29[i] != img[i] and not any(x <= B + i < y for x, y, _ in ALLOWED_DIFF):
                    bad.append((k, hex(B + i)))
        nd = sum(v29[i] != img[i] for k, (lo, hi) in WINDOWS.items() for i in range(lo - B, hi - B))
        report(f'W {len(WINDOWS)} windows identical in final and v0.29a', not bad,
               f'{nd} differing bytes, all in the allowed list (setting 270 record; film-menu label hooks A/B)' if not bad else str(bad[:6]))
        # C  no other Caduceus edit of v0.29a lies in a range claimed by a module of the final (shared tables, shared tail, ...)
        import fork_build as FB
        rel = json.loads(a.v029a.read_text())
        hits = []
        for m, comps in FB.STOCK_MODULES.items():
            for lo, hi, why in comps['0x100']:
                for e in rel['edits']:
                    if e['kind'] == '0x100' and not e['addr'].startswith('off:'):
                        x, n = int(e['addr'], 16), len(e['new']) // 2
                        if x < hi and lo < x + n and e.get('source') != f'patches/{m}':
                            hits.append((m, hex(lo), e['addr'], e.get('source')))
        report('C no other v0.29a edit overlaps a module range of the final', not hits, str(hits[:6]) if hits else
               f'{sum(len(c["0x100"]) for c in FB.STOCK_MODULES.values())} ranges checked against {len(rel["edits"])} edits')
        # X
        Img29 = V.Img(v29)
        ok = True
        sids = [46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 571, 572, 573, 1266, 1269, 1271]
        for sid in sids:
            ok &= Img29.listed(sid) == P.listed(sid)
        report(f'X validator count/value of {len(sids)} sids: final == v0.29a', ok)
        ok = True
        for sid, lst in [(s, b['full']) for s in b['full_sids']] + [(s, b['dpad']) for s in b['dpad_sids']]:
            ok &= [Img29.next(sid, v) for v in lst] == [P.next(sid, v) for v in lst]
        report('X dial stepping of sids 47/48/49/51/53 over every listed code: final == v0.29a', ok)
        codes = sorted(set(b['full'] + b['dpad']))
        ok = all(Img29.disp(V.FUNC2ACT, c) == P.disp(V.FUNC2ACT, c) for c in codes) and \
            all(Img29.disp(V.SID2KIND, s) == P.disp(V.SID2KIND, s) for s in range(47, 54))
        report(f'X function -> action for {len(codes)} codes and key kinds of sids 47-53: final == v0.29a', ok)
        if LV is None:
            report('X LCD panel routine: NOT RUN (needs numpy)', False, LV_ERR)
        else:
            stub = LV.memcpy_stub()
            ok, n = True, 0
            for br in (0, 7, 14):
                for c in range(15):
                    r1, b1 = LV.panel_run(v29, stub, br, c)
                    r2, b2 = LV.panel_run(img, stub, br, c)
                    ok &= r1 and r2 and b1 == b2
                    n += 1
            report(f'X LCD panel routine 0x60184360: {n} (brightness x colour step) SPI buffers final == v0.29a', ok)
    print('ALL PASS' if all(results) else 'FAILURES')
    sys.exit(0 if all(results) else 1)


if __name__ == '__main__':
    main()
