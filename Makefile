# Firmware builds of this fork (stock E-P7 1.1 + our patches). Nothing here flashes a camera or writes to an SD card.
#   make stock               check (or download and verify) the official stock firmware
#   make minimal             stock + jpeg_always + lever_nomenu            -> out/minimal/
#   make final               minimal + lcd_tint + more button functions + version label -> out/final/
#   make final_emu           emulator test of the jpeg_always stub inside the final image (slow)
#   make clean               remove out/
# If Python 3.15 cannot open network sockets on your Mac, use: make stock PY=/usr/bin/python3
PY   ?= python3

.PHONY: stock jpeg_always_stock minimal jpeg_always_stock_emu final final_emu clean

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

# FINAL firmware (docs/FINAL_BUILD.md): stock + jpeg_always + lever_nomenu + lcd_tint + more button functions (omc_buttons + btn_arrows) + dial_expcomp (M/B dial: Shutter / Exp comp) + profile_lsf (profile JPEG on the first quality slot) + dial_iso (M: free dial sets ISO without lens contacts) + fw_version (Setup > Firmware: "phocean" / "1.0").
# Nothing else of Caduceus. 0x101 stays the stock payload. The package hashes are pinned below (a change is refused, nothing written).
#   MAIN : the main checkout, which holds external/oly_fw_analysis (emulator engine); default = this directory.
#   PYNP : a Python with numpy (tools/ep7_verify_lcd_tint.py and patches/final/verify.py import it); default = $(PY).
MAIN  ?= $(CURDIR)
PYNP  ?= $(PY)
EMU_ENV = EP7_MAIN_REPO=$(MAIN) PYTHONPATH=$(MAIN)/external/oly_fw_analysis/tools
FINAL_MODULES = --module jpeg_always --module lever_nomenu --module lcd_tint --module omc_buttons --module btn_arrows --module fw_version --module dial_expcomp --module profile_lsf --module dial_iso
FINAL_SHA         = e30815a7d97f8356083835490e2d8ac831366e250fcd1f97807b7e0810242792
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

# Emulator test of the jpeg_always stub inside the FINAL image (about 1.5 to 7 minutes).
final_emu:
	EP7_MAIN_REPO=$(MAIN) EP7_STOCK_MAIN=$(CURDIR)/analysis/ep7_1100/00_0100_406a0020.decoded.bin \
	  $(PY) -I patches/jpeg_always/emu_verify.py --base final --final-spec generated/final/edits.json

clean:
	rm -rf out
