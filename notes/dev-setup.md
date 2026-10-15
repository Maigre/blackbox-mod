# Dev setup — build and test this fork on a Linux box (no root needed)

Done on mgr-ran 2026-10-15; the same recipe equips dev37 (the loop box) or any Linux machine.

```sh
# 1. Toolchain + Ghidra under /srv/dev (any user-writable prefix works)
mkdir -p /srv/dev/dl /srv/dev/toolchains /srv/dev/venvs /srv/dev/firmware/docs
cd /srv/dev/dl
curl -sLO https://developer.arm.com/-/media/Files/downloads/gnu/14.2.rel1/binrel/arm-gnu-toolchain-14.2.rel1-x86_64-arm-none-eabi.tar.xz
gh release download --repo NationalSecurityAgency/ghidra --pattern 'ghidra_*_PUBLIC_*.zip' -D .   # needs Java 21+
cd /srv/dev/toolchains
tar -xJf /srv/dev/dl/arm-gnu-toolchain-14.2.rel1-x86_64-arm-none-eabi.tar.xz && mv arm-gnu-toolchain-14.2.rel1-x86_64-arm-none-eabi arm-gnu-14.2
unzip -q /srv/dev/dl/ghidra_*_PUBLIC_*.zip -d /srv/dev/toolchains        # -> /srv/dev/toolchains/ghidra_12.1.4_PUBLIC

# 2. Python venv for the Unicorn suites and pyghidra
uv venv --python 3.12 /srv/dev/venvs/bb
VIRTUAL_ENV=/srv/dev/venvs/bb uv pip install unicorn capstone numpy scipy pyghidra

# 3. The stock firmware, once, outside every clone (public download from 1010music; never in git)
#    /srv/dev/firmware/BLACKBOX-3.1.9.bin  sha256 281ae303d32e5eb52adca7817a648a34e4bd3848017f26673dd9df3905f1341d

# 4. In the clone
cd ~/Bakery/blackbox-mod
ln -sf /srv/dev/firmware/BLACKBOX-3.1.9.bin firmware/BLACKBOX-3.1.9.bin   # gitignored
ln -sfn /srv/dev/venvs/bb .venv && echo .venv >> .git/info/exclude        # check.sh prefers .venv/bin/python
export PATH=/srv/dev/toolchains/arm-gnu-14.2/bin:$PATH
./check.sh            # build (dev), patch every set, run the 30 suites -> "30 suites, 0 failed"
```

Release images (what goes on the card): `RELEASE=1 ./build.sh && python3 patch.py cave` (cave-only) or the
full set `python3 patch.py solo slice duck chord cond filter cpu od comp seqfix fx2 munchi master fault cave`.
`RELEASE=1` compiles the USB peek/poke out and shows `RELEASE_NAME` (`src/release.h`, `MAIGRE 1`) on TOOLS.
**Rebuild without `RELEASE=1` before running the suites** (they expect the dev build). The two Gate 0 images of
2026-10-15 sit in `out/gate0/{cave,full}/BLACKBOX.bin`; `BBEXTRA.BIN` is not installed for now (D-008).

Ghidra (the RE helpers in `ghidra/`): the scripts default to the Homebrew paths and read `GHIDRA_INSTALL_DIR`,
`JAVA_HOME` and `GHIDRA_PROJ` (where the analysed project lives; default `ghidra/`) from the environment. Keep the
project outside the clone so a fresh checkout or a loop worktree can reuse it:

```sh
export JAVA_HOME=/srv/dev/toolchains/jdk-21 GHIDRA_INSTALL_DIR=/srv/dev/toolchains/ghidra_12.1.4_PUBLIC GHIDRA_PROJ=/srv/dev/firmware/ghidra
mkdir -p "$GHIDRA_PROJ" && /srv/dev/venvs/bb/bin/python ghidra/import.py       # once: import + auto-analysis, 2,577 functions
/srv/dev/venvs/bb/bin/python ghidra/gq.py callers 0x0808c158                    # then any gq.py query
```

(dev37 has no system Java; `jdk-21` is a Temurin 21 tarball. mgr-ran has Java 25 on the system.)

Facts: this toolchain's output is not byte-identical to upstream's releases (D-010); the host CPU here has no FMA,
hence `HOST_TOL = 1e-5` in `test_machine.py` (D-009); `check.sh` always exits 0 and prints `N suites, M failed`,
so a verdict is `./check.sh 2>&1 | tail -1 | grep -q ', 0 failed'` — that line is the hub's `verify:`.
