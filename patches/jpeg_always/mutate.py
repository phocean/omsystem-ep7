#!/usr/bin/env python3
"""Mutation harness for patches/jpeg_always/verify.py: change one byte of the assembled stub, run verify.py, expect a failure.

  python3 -I patches/jpeg_always/mutate.py releases/v0.29a/edits.json generated/jpeg_always/edits.json
  python3 -I patches/jpeg_always/mutate.py stock generated/jpeg_always_stock/edits.json     # --base stock build

(set EP7_STOCK_MAIN as for build.py). Prints killed / total; exit 1 if any mutant survives. Offsets are CPU addresses of the
default build (both bases: the stub is the same) (jo_get at 0x601de540); the original byte is checked first so a changed stub makes the harness stop, not pass.
"""
import json, os, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
AT = 0x601de540
SPAN = 0x605b7755                                  # SD loader v3 per-byte span of slot byte +52 (must stay 1: migration from jpeg_only)
# name: (address, original byte, mutated byte)
MUTANTS = {
    'exth d2 -> exthu d2 (key compare)': (0x601de541, 0x1a, 0x1e),
    'cmp 0x5141 branch bne -> beq': (0x601de54d, 0xc9, 0xc8),
    'slot-2 selector key 0x5131 -> 0x5132': (0x601de550, 0x31, 0x32),
    'slot-1 selector key 0x8141 -> 0x8142': (0x601de555, 0x41, 0x42),
    'selector read: clr d1 -> inc d1': (0x601de558, 0x04, 0x44),
    'selector read: mov 0,a0 -> mov 1,a0': (0x601de55a, 0x00, 0x01),
    'selector cmp 3 -> 5': (0x601de563, 0x03, 0x05),
    'selector cmp 3 -> 2': (0x601de563, 0x03, 0x02),
    'selector 3 test beq -> bne': (0x601de564, 0xc8, 0xc9),
    'selector cmp 4 -> 5': (0x601de567, 0x04, 0x05),
    'mode key 0x9481 -> 0x9482': (0x601de56b, 0x81, 0x82),
    'mode read: clr d1 -> inc d1': (0x601de56e, 0x04, 0x44),
    'mode-6 cmp 6 -> 7': (0x601de579, 0x06, 0x07),
    'mode-6 test bne -> beq': (0x601de57a, 0xc9, 0xc8),
    'mode-6 key 0x9d11 -> 0x9d12': (0x601de57d, 0x11, 0x12),
    'mode-6 read: clr d1 -> inc d1': (0x601de580, 0x04, 0x44),
    'mode 11 -> 10': (0x601de58b, 0x0b, 0x0a),
    'mode 11 test beq -> bne': (0x601de58c, 0xc8, 0xc9),
    'mode 12 -> 13': (0x601de58f, 0x0c, 0x0d),
    'pass: exthu d0 dropped (clr d0)': (0x601de593, 0x1c, 0x00),
    'pass: mov d3,d1 -> exthu d0 (d1 not restored)': (0x601de594, 0x8d, 0x1c),
    'pass: mov 0,a0 -> mov 1,a0': (0x601de596, 0x00, 0x01),
    'override: mov d3,d1 -> exthu d0 (idx not restored)': (0x601de59e, 0x8d, 0x1c),
    'override: mov 0,a0 -> mov 1,a0': (0x601de5a0, 0x00, 0x01),
    'override: clr d2 -> inc d2': (0x601de5a1, 0x08, 0x48),
    'override ret frame 12 -> 8': (0x601de5ac, 0x0c, 0x08),
}


def main():
    base, spec = Path(sys.argv[1]), Path(sys.argv[2])
    d = json.loads(spec.read_text())
    e = next(x for x in d['edits'] if x['addr'] == hex(AT))
    code = bytearray.fromhex(e['new'])
    killed = 0
    with tempfile.TemporaryDirectory() as t:
        for name, (addr, old, new) in MUTANTS.items():
            if code[addr - AT] != old:
                sys.exit(f'{name}: byte at {addr:#x} is {code[addr - AT]:#04x}, expected {old:#04x} (stub changed: update MUTANTS)')
            c = bytearray(code)
            c[addr - AT] = new
            m = json.loads(json.dumps(d))
            next(x for x in m['edits'] if x['addr'] == hex(AT))['new'] = c.hex()
            f = Path(t) / 'mut.json'
            f.write_text(json.dumps(m))
            r = subprocess.run([sys.executable, '-I', str(HERE / 'verify.py'), str(base), str(f)], capture_output=True, text=True, env=dict(os.environ))
            dead = r.returncode != 0
            killed += dead
            print(f'{"killed  " if dead else "SURVIVED"} {name}')
        total = len(MUTANTS)
        if d['jpeg_always']['base'] == 'release':           # migration mutant: the loader span of +52 back to 0 must be caught (BUNDLES.BIN +52 = 1)
            total += 1
            m = json.loads(json.dumps(d))
            for x in m['edits']:
                if not x['addr'].startswith('off:') and int(x['addr'], 16) <= SPAN <= int(x['addr'], 16) + len(x['new']) // 2 - 1:
                    b = bytearray.fromhex(x['new'])
                    assert b[SPAN - int(x['addr'], 16)] == 1
                    b[SPAN - int(x['addr'], 16)] = 0
                    x['new'] = b.hex()
            f = Path(t) / 'mut.json'
            f.write_text(json.dumps(m))
            r = subprocess.run([sys.executable, '-I', str(HERE / 'verify.py'), str(base), str(f)], capture_output=True, text=True, env=dict(os.environ))
            killed += r.returncode != 0
            print(f'{"killed  " if r.returncode else "SURVIVED"} migration: loader span[52] 1 -> 0 (BUNDLES.BIN +52 = 1 would be rejected)')
    print(f'{killed}/{total} mutants killed')
    sys.exit(0 if killed == total else 1)


if __name__ == '__main__':
    main()
