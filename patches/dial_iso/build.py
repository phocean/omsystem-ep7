#!/usr/bin/env python3
"""dial_iso (design A2): M-mode free dial assigned to "FNo." becomes ISO when no contact lens is connected. Offline. docs/DIAL_ISO.md.

  python3 -I patches/dial_iso/build.py [--out patches/dial_iso/edits.json] [--stock-main PATH]   ($EP7_STOCK_MAIN overrides the stock path)

Writes edits.json ({components, edits}; 2 edits of kind 0x100, `expect` = the stock bytes read from the decoded stock main):
  hook  0x60cdc837  9 B  `mov d0,a3 ; call 0x60cc8be9,[d2,d3],8`  ->  `jmp dl_fn ; nop x4`   (resume 0x60cdc840)
  stub  0x60210900  60 B  dl_fn (dial_iso.s.in), tail of section 1 (stock FF 0x602108ec..0x60211000)
Ranges for tools/fork_build.py STOCK_MODULES (printed, and asserted here): stub (0x60210900, 0x6021093c), hook (0x60cdc837, 0x60cdc840).

Refusals (nothing is written): the hook bytes / resume instruction / callee prologues and frames are not stock; the zone is not FF or the 20-byte
guard in front is not; any abs32 word (cached, uncached, flash-logical, flash-uncached alias; any byte offset) or jmp / call / calls / bcc
encoding points into the claim (known false positives in the guards are pinned); a branch from outside lands inside the hook's 9 bytes
(other than at its start); misaligned stub; size over the claim; mul / div / setlb / trap / lxx; an fb-prefixed form; any store; any call or jmp
other than the three callee frames and the resume; a branch target that is not an instruction boundary; a section load-order violation.
"""
import argparse, json, os, re, struct, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
BASE = 0x60020020
STOCK = Path(os.environ.get('EP7_STOCK_MAIN') or ROOT / 'analysis/ep7_1100/00_0100_406a0020.decoded.bin')
TC = Path.home() / 'ep7fw-toolchains/mn10300/bin'
SRC = 'patches/dial_iso'

AT, END = 0x60210900, 0x6021093c                    # stub claim (60 B)
ZONE = (0x602108ec, 0x60211000)                     # stock FF tail of section 1
GUARD = 16                                          # FF kept in front of / behind the claim for the reference scan (the 20 B 0x602108ec..0x60210900 are all FF)
HOOK, HOOK_END, RESUME = 0x60cdc837, 0x60cdc840, 0x60cdc840
HOOK_STOCK = bytes.fromhex('f1e3ddb0c3feffc008')    # mov d0,a3 ; call 0x60cc8be9,[d2,d3],8
GETSID, LENS, RULE = 0x60ccf9f3, 0x602ea74c, 0x60cc8be9
FN_START, FN_END = 0x60cdc82c, 0x60cdcbde            # the dial routine (ret [d2,d3,a2,a3],56 at its ends)
FRAMES = {GETSID: ('d2,a2', 24), LENS: ('d2', 28), RULE: ('d2,d3', 8)}
# stock prologue bytes of the three callees, and the return frame each of them ends with (so a frame can not drift silently)
CALLEE = {GETSID: ('82 2c800c 4204'.replace(' ', ''), 0x60ccfa43, 'df a0 18'.replace(' ', '')),     # mov d0,d2 ... ret [d2,a2],24
          LENS: ('8004 8501'.replace(' ', ''), 0x602ea78e, 'df80'),                                 # ... ret [d2],28
          RULE: ('0cfac8800c', 0x60cc8c08, 'dec008')}                                               # clr d3 ... retf [d2,d3],8
# the nine sections, load order 1, 7, 2, 3, 4, 5, 6, 8, 9 (docs/FIRMWARE_GUIDE.md section 2)
SECTIONS = {1: (0x600d7800, 0x60211000), 2: (0x60280800, 0x6055e800), 3: (0x6057b200, 0x605b7800), 4: (0x605baa00, 0x60748000),
            5: (0x6075a800, 0x60b9e000), 6: (0x60ba7000, 0x61243000), 7: (0x612c7000, 0x61379000), 9: (0x613c1000, 0x6143a800)}
LOAD_ORDER = [1, 7, 2, 3, 4, 5, 6, 8, 9]
SEC1_FLASH_LOGICAL = 0x40757800 - 0x600d7800        # descriptor {start 0x600d7800, logical source 0x40757800, dest 0x600d7800}
BAD = {'mul', 'mulu', 'div', 'divu', 'setlb', 'llt', 'lne', 'leq', 'lra', 'lcc', 'lcs', 'trap', 'ext', 'extb', 'extbu', 'exth'}
# known false positives in the guards (any alias, any byte offset), pinned with the bytes around them after a disassembly check:
# 0x6086f774 `f0 08 21 60` is `mov (a0),a2 ; add 96,a1` (0x6086f774..0x6086f778 of startup-time UI code), value 0x602108f0
FALSE_HITS = {0x6086f774: ('3df0082160f82a60', 0x602108f0)}      # bytes a-1 .. a+7


def section(a):
    for k, (lo, hi) in SECTIONS.items():
        if lo <= a < hi:
            return k


def sh(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, text=kw.pop('text', True), **kw)


def assemble(syms):
    src = (HERE / 'dial_iso.s.in').read_text()
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        (t / 'p.s').write_text(src)
        sh([TC / 'mn10300-elf-as', '-o', t / 'p.o', t / 'p.s'])
        sh([TC / 'mn10300-elf-ld', '-Ttext', hex(AT), '-e', '_start', *[f'--defsym={k}={v:#x}' for k, v in syms.items()], '-o', t / 'p.elf', t / 'p.o'])
        sh([TC / 'mn10300-elf-objcopy', '-O', 'binary', '-j', '.text', t / 'p.elf', t / 'p.bin'])
        nm = sh([TC / 'mn10300-elf-nm', t / 'p.elf']).stdout
        sy = {n: int(a, 16) for a, ty, n in (l.split() for l in nm.splitlines() if len(l.split()) == 3) if ty in 'tT'}
        return (t / 'p.bin').read_bytes(), sy, src


def disasm(code, at, stop=None):
    with tempfile.NamedTemporaryFile(suffix='.bin') as tf:
        tf.write(code)
        tf.flush()
        out = sh([TC / 'mn10300-elf-objdump', '-b', 'binary', '-m', 'am33-2', '-D', f'--adjust-vma={at:#x}',
                  f'--stop-address={(stop or at + len(code)):#x}', tf.name]).stdout
    return [(int(m.group(1), 16), m.group(2), m.group(3).strip(), m.group(0))
            for m in re.finditer(r'^\s*([0-9a-f]+):\t[0-9a-f ]+\t(\S+)[ \t]*(.*)$', out, re.M)], out


def s_(v, n):
    m = 1 << (8 * n)
    return v - m if v >= m // 2 else v


def abs32_hits(d, lo, hi):
    """32-bit words at any byte offset into [lo,hi): cached 0x6, uncached 0xa, flash-logical 0x4, flash-uncached 0x8 alias."""
    lg = SEC1_FLASH_LOGICAL
    wins = [(lo + k & 0xffffffff, hi + k & 0xffffffff) for k in (0, 0x40000000, lg, lg + 0x40000000)]
    out = []
    for sft in range(4):
        n = (len(d) - sft) // 4
        for i, v in enumerate(struct.unpack_from(f'<{n}I', d, sft)):
            for a, b in wins:
                if a <= v < b:
                    out.append((BASE + sft + 4 * i, v))
    return sorted(out)


def rel_hits(d, lo, hi, short):
    """jmp / call d32 / d16, calls d16 / d32 (and bcc d8 when `short`) at any byte offset whose target is in [lo,hi) -> [(addr, kind, target)]."""
    out = []
    for i in range(len(d) - 6):
        b, pc, t, k = d[i], BASE + i, None, None
        if b in (0xdc, 0xdd):
            t, k = pc + s_(struct.unpack_from('<I', d, i + 1)[0], 4), 'd32'
        elif b in (0xcc, 0xcd):
            t, k = pc + s_(struct.unpack_from('<H', d, i + 1)[0], 2), 'd16'
        elif b in (0xfa, 0xfc) and d[i + 1] == 0xff:
            n = 2 if b == 0xfa else 4
            t, k = pc + s_(int.from_bytes(d[i + 2:i + 2 + n], 'little'), n), 'calls'
        elif short and 0xc0 <= b <= 0xca:
            t, k = pc + s_(d[i + 1], 1), 'b8'
        if t is not None and lo <= t < hi:
            out.append((pc, k, t))
    return out


def checks(stock):
    log = {}
    # --- hook site
    if stock[HOOK - BASE:HOOK_END - BASE] != HOOK_STOCK:
        raise SystemExit(f'hook bytes at {HOOK:#x} are not stock: {stock[HOOK - BASE:HOOK_END - BASE].hex()}')
    if stock[HOOK + 2 - BASE] != 0xdd or HOOK + 2 + struct.unpack_from('<i', stock, HOOK + 3 - BASE)[0] != RULE or stock[HOOK + 7 - BASE:HOOK_END - BASE] != b'\xc0\x08':
        raise SystemExit('hook: second instruction is not `call 0x60cc8be9,[d2,d3],8`')
    if stock[RESUME - BASE:RESUME - BASE + 2] != bytes.fromhex('4220'):     # mov d0,(32,sp)
        raise SystemExit(f'resume {RESUME:#x} is not `mov d0,(32,sp)`')
    # the hook is mid-routine, straight line: the 9 bytes are two whole instructions of the routine (disassembly from the routine start)
    ins, _ = disasm(stock[FN_START - BASE:FN_END - BASE], FN_START)
    starts = {a for a, *_ in ins}
    if HOOK not in starts or HOOK + 2 not in starts or RESUME not in starts or any(HOOK < a < HOOK_END and a != HOOK + 2 for a in starts):
        raise SystemExit('hook bytes are not two whole instructions of the routine')
    # no branch of the routine itself lands inside (HOOK, HOOK_END)
    inner = []
    for a, op, args, _ in ins:
        m = re.match(r'0x([0-9a-f]+)', args)
        if m and (op[0] == 'b' or op in ('jmp', 'call', 'calls') or op.startswith('l')) and HOOK < int(m.group(1), 16) < HOOK_END:
            inner.append((hex(a), op, args))
    if inner:
        raise SystemExit(f'routine branch into the hook interior: {inner}')
    # global scan: branch encodings landing in (HOOK, HOOK_END) whose own address is outside the hook; abs32 words (any alias) likewise
    ext = [(hex(a), k, hex(t)) for a, k, t in rel_hits(stock, HOOK + 1, HOOK_END, True) if not HOOK <= a < HOOK_END]
    absr = [(hex(a), hex(v)) for a, v in abs32_hits(stock, HOOK + 1, HOOK_END)]
    if ext or absr:
        raise SystemExit(f'reference into the hook interior: {ext} {absr}')
    log['hook_interior_refs'] = 0
    # --- callees: prologue and return frame as assumed
    for t, (pro, ret_at, ret_b) in CALLEE.items():
        if stock[t - BASE:t - BASE + len(pro) // 2].hex() != pro:
            raise SystemExit(f'callee {t:#x} prologue differs from the study: {stock[t - BASE:t - BASE + len(pro) // 2].hex()}')
        if stock[ret_at - BASE:ret_at - BASE + len(ret_b) // 2].hex() != ret_b:
            raise SystemExit(f'callee {t:#x}: return frame at {ret_at:#x} is not {ret_b}')
    # callee bodies write none of the registers the stub keeps across them (a3 = function code, d3 = counter, a2 = ctx): the frame masks say the same
    bodies = {GETSID: (0x60ccfa46, ('d3', 'a3')), LENS: (0x602ea78f, ('d3', 'a2', 'a3'))}
    log['callee_direct_writes'] = {}
    for t, (end, forbidden) in bodies.items():
        bad = [(hex(a), op, args) for a, op, args, _ in disasm(stock[t - BASE:end - BASE], t)[0]
               if args.split(',')[-1].strip() in forbidden and op not in ('cmp', 'btst', 'call', 'calls', 'jmp', 'ret', 'retf', 'rets')]
        if bad:
            raise SystemExit(f'callee {t:#x} writes {forbidden}: {bad}')
        log['callee_direct_writes'][hex(t)] = f'none of {forbidden}'
    # the routine itself calls GETSID with the same frame at 0x60cdc876
    if stock[0x60cdc876 - BASE:0x60cdc87d - BASE] != b'\xdd' + struct.pack('<i', GETSID - 0x60cdc876) + b'\xa0\x18':
        raise SystemExit('0x60cdc876 is not `call getsid,[d2,a2],24`')
    # --- zone: FF, guard, no references into the claim
    if set(stock[ZONE[0] - BASE:ZONE[1] - BASE]) != {0xff}:
        raise SystemExit(f'{ZONE[0]:#x}..{ZONE[1]:#x} is not all FF in stock')
    if AT - GUARD < ZONE[0] or END + GUARD > ZONE[1]:
        raise SystemExit('claim + guards outside the FF zone')
    if AT - ZONE[0] < 16:
        raise SystemExit('FF guard in front of the claim is shorter than 16 bytes')
    h = abs32_hits(stock, AT, END)
    if h:
        raise SystemExit(f'abs32 words point into the claim: {[(hex(a), hex(v)) for a, v in h]}')
    gh = [(a, v) for lo, hi in ((AT - GUARD, AT), (END, END + GUARD)) for a, v in abs32_hits(stock, lo, hi)]
    for a, v in gh:
        pin = FALSE_HITS.get(a)
        if not pin or stock[a - 1 - BASE:a - 1 - BASE + 8].hex() != pin[0] or v != pin[1]:
            raise SystemExit(f'abs32 word {a:#x} -> {v:#x} points into a guard (not a pinned false positive)')
    r = rel_hits(stock, AT - GUARD, END + GUARD, True)
    if r:
        raise SystemExit(f'jmp / call / bcc encodings target the claim or its guards: {[(hex(a), k, hex(t)) for a, k, t in r]}')
    log['abs32_in_claim'] = 0
    log['guard_false_positives'] = [hex(a) for a, _ in gh]
    log['zone_ff'] = f'{ZONE[0]:#x}..{ZONE[1]:#x}'
    return log


def sections_check():
    if section(AT) != 1 or section(END - 1) != 1:
        raise SystemExit('stub must be inside section 1')
    sh_, st = section(HOOK), section(AT)
    if sh_ is None or LOAD_ORDER.index(sh_) <= LOAD_ORDER.index(st):
        raise SystemExit(f'hook (section {sh_}) is not loaded after the stub (section {st})')
    if section(RESUME) != sh_ or section(FN_START) != sh_:
        raise SystemExit('routine / resume not in the hook section')
    return dict(stub=st, hook=sh_, order=LOAD_ORDER)


def build(stock):
    code, sy, src = assemble(dict(ep7_getsid=GETSID, ep7_lens=LENS, ep7_rule=RULE, ep7_resume=RESUME))
    if sy.get('dl_fn') != AT or AT % 4:
        raise SystemExit('dl_fn must be at the claim start, 4-byte aligned')
    if len(code) > END - AT:
        raise SystemExit(f'stub {len(code)} B > claim {END - AT} B')
    if AT + len(code) != END:
        raise SystemExit(f'stub ends at {AT + len(code):#x}, the declared claim end is {END:#x}')
    ins, dis = disasm(code, AT)
    if not ins or ins[0][0] != AT:
        raise SystemExit('disassembly does not start at dl_fn')
    if any(op in BAD for _, op, _, _ in ins if op != 'exthu'):
        raise SystemExit('forbidden instruction: ' + ', '.join(f'{a:#x} {op}' for a, op, _, _ in ins if op in BAD))
    if any(code[a - AT] == 0xfb for a, *_ in ins):
        raise SystemExit('fb-prefixed form')
    for a, op, args, _ in ins:
        if '(' in args.split(',')[-1] and op.startswith('mov') or op == 'movm':
            raise SystemExit(f'store at {a:#x}: {op} {args}')
        if op.startswith('mov') and '(' in args:
            raise SystemExit(f'memory access at {a:#x}: {op} {args} (the stub reads/writes no memory)')
    last = ins[-1]
    if last[1] != 'jmp' or int(last[2].split()[0], 16) != RESUME or END - AT != (last[0] - AT) + 5:
        raise SystemExit('stub must end with `jmp 0x60cdc840` exactly at the end of the claim')
    bounds = {a for a, *_ in ins}
    calls = []
    for a, op, args, _ in ins:
        m = re.match(r'0x([0-9a-f]+)(?:,\[([a-z0-9,]*)\],(\d+))?', args)
        if op in ('call', 'calls', 'jmp', 'ret', 'retf', 'rets', 'rts') or op.startswith(('b',)) and m:
            if op == 'call':
                t = int(m.group(1), 16)
                if t not in FRAMES or (m.group(2), int(m.group(3))) != FRAMES[t]:
                    raise SystemExit(f'call {a:#x}: {args}: unexpected target/frame')
                calls.append((a, t))
            elif op == 'jmp':
                if int(m.group(1), 16) != RESUME and not AT <= int(m.group(1), 16) < END:
                    raise SystemExit(f'jmp {a:#x} -> {args}')
            elif op.startswith('b') and m:
                if int(m.group(1), 16) not in bounds:
                    raise SystemExit(f'branch {a:#x} -> {args} is not an instruction boundary of the stub')
            else:
                raise SystemExit(f'stub returns by itself ({op} at {a:#x})')
    if sorted(t for _, t in calls) != sorted([GETSID, GETSID, LENS, RULE]):
        raise SystemExit(f'call set {[(hex(a), hex(t)) for a, t in calls]}')
    # registers written by the stub (other than through the callees' own frames): d0, a3 (+ scratch d1 a0 a1 via the calls, as the displaced call)
    written = sorted({args.split(',')[-1].strip() for _, op, args, _ in ins if op in ('mov', 'exthu') and args.split(',')[-1].strip() in ('d0', 'd1', 'd2', 'd3', 'a0', 'a1', 'a2', 'a3')} |
                     ({'d0'} if any(op == 'exthu' and args == 'd0' for _, op, args, _ in ins) else set()))
    if written != ['a3', 'd0']:
        raise SystemExit(f'direct register writes {written} != [a3, d0]')
    jmp = b'\xdc' + struct.pack('<i', AT - HOOK) + b'\xcb' * 4
    assert len(jmp) == HOOK_END - HOOK
    return code, jmp, sy, ins, dis, src, written


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', type=Path, default=HERE / 'edits.json')
    ap.add_argument('--stock-main', type=Path)
    ap.add_argument('--print-dis', action='store_true')
    a = ap.parse_args()
    global STOCK
    if a.stock_main:
        STOCK = a.stock_main
    stock = STOCK.read_bytes()
    log = checks(stock)
    log['sections'] = sections_check()
    code, jmp, sy, ins, dis, src, written = build(stock)
    exp_stub = stock[AT - BASE:AT - BASE + len(code)]
    if set(exp_stub) != {0xff}:
        raise SystemExit('stock bytes under the stub are not FF')
    spec = dict(components=['0x100'], edits=[
        dict(kind='0x100', addr=hex(HOOK), expect=HOOK_STOCK.hex(), new=jmp.hex(), source=SRC,
             why='dial_iso: in the dial routine 0x60cdc82c, `mov d0,a3 ; call 0x60cc8be9,[d2,d3],8` -> `jmp 0x60210900 ; nop x4` (resume 0x60cdc840). M mode, dial function FNo. (3) with no contact lens -> ISO (6).'),
        dict(kind='0x100', addr=hex(AT), expect=exp_stub.hex(), new=code.hex(), source=SRC,
             why=f'dial_iso: dl_fn ({len(code)} B, section-1 FF tail 0x60210900..0x6021093c): replays the displaced instructions, a3 = 6 when fn == 3 and mode key == 6 and 0x602ea74c() == 0, then jmp 0x60cdc840.')])
    a.out.write_text(json.dumps(spec, indent=1) + '\n')
    print(f'wrote {a.out}')
    print(f'stub  {AT:#x}..{END:#x} ({len(code)} B)  fork_build range: ({AT:#x}, {END:#x})')
    print(f'hook  {HOOK:#x}..{HOOK_END:#x} (9 B)   fork_build range: ({HOOK:#x}, {HOOK_END:#x})   resume {RESUME:#x}')
    print('hook bytes:', jmp.hex(), ' stub:', code.hex())
    print('checks:', json.dumps(log))
    print('direct register writes:', written)
    if a.print_dis:
        print(dis)


if __name__ == '__main__':
    main()
