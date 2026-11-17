# Firmware builds of this fork (stock E-P7 1.1 + our patches). Nothing here flashes a camera or writes to an SD card.
#   make setup               ONE TIME: venv + numpy, submodule, mn10300 binutils, emulator, OM's stock firmware (tools/setup.sh)
#   make firmware            builds, verifies and prints the update file and the restore file (= make final with the venv)
#   make stock               check (or download and verify) the official stock firmware
#   make minimal             stock + jpeg_always + lever_nomenu            -> out/minimal/
#   make final               minimal + lcd_tint + more button functions + version label -> out/final/
#   make final_emu           emulator test of the jpeg_always stub inside the final image (slow)
#   make clean               remove out/
# If Python 3.15 cannot open network sockets on your Mac, use: make stock PY=/usr/bin/python3
PY   ?= $(if $(wildcard $(CURDIR)/.venv/bin/python),$(CURDIR)/.venv/bin/python,python3)
export EP7_TOOLCHAIN ?= $(HOME)/ep7fw-toolchains
export PYTHON ?= $(PY)

.PHONY: setup firmware stock jpeg_always_stock minimal jpeg_always_stock_emu final final_nocode final_emu clean

setup:
	tools/setup.sh

firmware:
	@test -x $(CURDIR)/.venv/bin/python || { echo "Run  make setup  first (one time)."; exit 1; }
	$(MAKE) final
	@echo
	@echo "Update file for the SD card:  out/final/DCOLYMP/E1429999.BIN"
	@echo "Restore file (stock firmware): out/final/restore/E1429999.BIN   (keep it on your computer)"
	@shasum -a 256 out/final/DCOLYMP/E1429999.BIN out/final/restore/E1429999.BIN 2>/dev/null || sha256sum out/final/DCOLYMP/E1429999.BIN out/final/restore/E1429999.BIN
	@echo "Next: copy the update file to DCOLYMP/E1429999.BIN on the SD card, see docs/INSTALL.md"

stock:
	$(PY) tools/fork_build.py stock
JA_ENV = EP7_MAIN_REPO=$(CURDIR) EP7_STOCK_MAIN=$(CURDIR)/analysis/ep7_1100/00_0100_406a0020.decoded.bin

# Stock firmware + jpeg_always only: no Caduceus release, no EP7MOD folder, no SD loader edit, no version label.
jpeg_always_stock: stock
	$(JA_ENV) $(PY) -I patches/jpeg_always/build.py --base stock --out generated/jpeg_always_stock/edits.json
	$(JA_ENV) $(PY) -I patches/jpeg_always/verify.py stock generated/jpeg_always_stock/edits.json
	$(JA_ENV) $(PY) -I patches/jpeg_always/mutate.py stock generated/jpeg_always_stock/edits.json
	$(PY) tools/fork_build.py build --base stock --spec generated/jpeg_always_stock/edits.json --out out/jpeg_always_stock

# Minimal firmware: stock + jpeg_always + lever_nomenu (one byte). Nothing else.
minimal: stock
	$(JA_ENV) $(PY) -I patches/jpeg_always/build.py --base stock --out generated/jpeg_always_stock/edits.json
	$(JA_ENV) $(PY) -I patches/jpeg_always/verify.py stock generated/jpeg_always_stock/edits.json
	$(PY) tools/fork_build.py build --base stock --spec generated/jpeg_always_stock/edits.json --patch patches/lever_nomenu/edits.json --out out/minimal

jpeg_always_stock_emu:
	$(JA_ENV) $(PY) -I patches/jpeg_always/emu_verify.py --base stock

# FINAL firmware (docs/FINAL_BUILD.md): stock + jpeg_always + lever_nomenu + lcd_tint + more button functions (omc_buttons + btn_arrows) + dial_expcomp (M/B dial: Shutter / Exp comp and Shutter / FNo.) + profile_lsf (profile JPEG on the first quality slot) + dial_iso (M: free dial FNo. -> ISO without lens contacts, Exp comp -> FNo. with contacts) + fw_version (Setup > Firmware: "phocean" / "1.1").
# Nothing else of Caduceus. 0x101 stays the stock payload. The package hashes are pinned below (a change is refused, nothing written).
#   MAIN : the main checkout, which holds external/oly_fw_analysis (emulator engine); default = this directory.
#   PYNP : a Python with numpy (tools/ep7_verify_lcd_tint.py and patches/final/verify.py import it); default = $(PY).
MAIN  ?= $(CURDIR)
PYNP  ?= $(PY)
EMU_ENV = EP7_MAIN_REPO=$(MAIN) PYTHONPATH=$(MAIN)/external/oly_fw_analysis/tools
FINAL_MODULES = --module jpeg_always --module lever_nomenu --module lcd_tint --module omc_buttons --module btn_arrows --module fw_version --module dial_expcomp --module profile_lsf --module dial_iso
FINAL_SHA         = b1c3f7c8aeec50d408db6416131d51064b029a9582b6fa96a5a29693258eb516
FINAL_RESTORE_SHA = 963f4dfe560e29216862c96284c92225f49977fd831a2ed60fa3ebbddf6d2327
final: stock
	$(JA_ENV) $(PY) -I patches/jpeg_always/build.py --base stock --out generated/jpeg_always_stock/edits.json
	$(JA_ENV) $(PY) -I patches/jpeg_always/verify.py stock generated/jpeg_always_stock/edits.json
	$(JA_ENV) $(PY) -I patches/jpeg_always/mutate.py stock generated/jpeg_always_stock/edits.json
	$(PY) -I patches/final/build.py --jpeg generated/jpeg_always_stock/edits.json --out generated/final/edits.json
	$(PY) -I patches/final/build.py --jpeg generated/jpeg_always_stock/edits.json --without lcd_tint --out generated/final/without_lcd_tint.json
	$(PY) -I patches/final/build.py --jpeg generated/jpeg_always_stock/edits.json --without omc_buttons --out generated/final/without_omc_buttons.json
	$(PY) -I patches/final/build.py --jpeg generated/jpeg_always_stock/edits.json --without btn_arrows --out generated/final/without_btn_arrows.json
	$(PY) -I patches/final/build.py --jpeg generated/jpeg_always_stock/edits.json --without fw_version --out generated/final/without_fw_version.json
	rm -rf out/final
	$(PY) tools/fork_build.py build --base stock --spec generated/final/edits.json $(FINAL_MODULES) \
	  --expect-sha256 $(FINAL_SHA) --expect-restore-sha256 $(FINAL_RESTORE_SHA) --out out/final
	@test -f generated/osd/strings_en.json || $(PY) -I tools/osd_extract.py > /dev/null
	$(EMU_ENV) $(PY) tools/ep7_buttons_verify.py generated/final/edits.json
	$(EMU_ENV) $(PY) patches/btn_arrows/verify.py generated/final/without_btn_arrows.json generated/final/edits.json
	$(EMU_ENV) $(PYNP) tools/ep7_verify_lcd_tint.py generated/final/edits.json --base generated/final/without_lcd_tint.json
	$(EMU_ENV) $(PY) patches/lever_nomenu/verify.py
	$(EMU_ENV) $(PY) patches/fw_version/verify.py generated/final/edits.json
	$(PY) -I patches/dial_expcomp/verify.py
	$(PY) -I patches/profile_lsf/verify.py
	$(EMU_ENV) $(PY) -I patches/dial_iso/verify.py
	$(EMU_ENV) $(PYNP) patches/final/verify.py generated/final/edits.json generated/final/without_omc_buttons.json --pkg out/final \
	  $(if $(wildcard releases/v0.29a/edits.json),--v029a releases/v0.29a/edits.json)
	@cat out/final/SHA256SUMS

# FINAL without the code module dial_iso (data modules only): the first flash of a two-step install (docs/FINAL_BUILD.md).
# Run `make final` first (it writes generated/final/edits.json and verifies every module).
FINAL_NOCODE_MODULES = --module jpeg_always --module lever_nomenu --module lcd_tint --module omc_buttons --module btn_arrows --module fw_version --module dial_expcomp --module profile_lsf
final_nocode:
	$(PY) -I patches/final/build.py --jpeg generated/jpeg_always_stock/edits.json --without dial_iso --out generated/final/without_dial_iso.json
	rm -rf out/final_nocode
	$(PY) tools/fork_build.py build --base stock --spec generated/final/without_dial_iso.json $(FINAL_NOCODE_MODULES) \
	  --expect-restore-sha256 $(FINAL_RESTORE_SHA) --out out/final_nocode
	@cat out/final_nocode/SHA256SUMS

# Emulator test of the jpeg_always stub inside the FINAL image (about 1.5 to 7 minutes).
final_emu:
	EP7_MAIN_REPO=$(MAIN) EP7_STOCK_MAIN=$(CURDIR)/analysis/ep7_1100/00_0100_406a0020.decoded.bin \
	  $(PY) -I patches/jpeg_always/emu_verify.py --base final --final-spec generated/final/edits.json

clean:
	rm -rf out
