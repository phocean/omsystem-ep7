# Notes for agents

Start with [`docs/FIRMWARE_GUIDE.md`](docs/FIRMWARE_GUIDE.md): how the E-P7 1.1 firmware is built, how to patch it
safely, and the lessons behind each safety rule. Every patch is a module under `patches/` with a builder and a verifier;
`patches/final/build.py` composes them and `tools/fork_build.py` writes the package. Before any new patch is offered
for flashing: emulator test, a security review, a stock restore file that has been tried, one feature group per flash.

Some documents cite files that only exist in the upstream project (cakelesscoder/caduceus-ep7); see `docs/UPSTREAM.md`.
