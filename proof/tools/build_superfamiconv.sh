#!/usr/bin/env bash
# Build SuperFamiconv (Optiroc, MIT) from source for the Retrogaze SNES proof: an independent encoder used as an
# oracle for code mode's 4bpp tile bytes (spec §5.2, test M2-15).
#
#   proof/tools/build_superfamiconv.sh <src-dir> <install-prefix>
#
# <src-dir>         checkout of Optiroc/SuperFamiconv at SFC_COMMIT; fetched there (shallow) if missing.
# <install-prefix>  receives bin/superfamiconv and SFC_COMMIT.
# Idempotent: does nothing when <install-prefix>/SFC_COMMIT already names the pinned commit.
# Build needs: git, cmake, a C++17 compiler. It is a test tool only: never linked or shipped.
set -euo pipefail

SFC_REPO=https://github.com/Optiroc/SuperFamiconv.git
SFC_COMMIT=fda06602e62ba04391eca488ae4f2697916907d5   # tag v0.9.2

if [ $# -ne 2 ]; then
  echo "usage: $0 <src-dir> <install-prefix>" >&2
  exit 2
fi
src=$1
prefix=$2

if [ -x "$prefix/bin/superfamiconv" ] && [ "$(cat "$prefix/SFC_COMMIT" 2>/dev/null)" = "$SFC_COMMIT" ]; then
  echo "build_superfamiconv: $prefix/bin/superfamiconv is already built from $SFC_COMMIT"
  exit 0
fi
for tool in git cmake c++; do
  command -v "$tool" >/dev/null || { echo "build_superfamiconv: missing tool: $tool" >&2; exit 1; }
done
if [ ! -d "$src" ]; then
  git init -q "$src"
  git -C "$src" fetch -q --depth 1 "$SFC_REPO" "$SFC_COMMIT"
  git -C "$src" checkout -q --detach FETCH_HEAD
fi
head=$(git -C "$src" rev-parse HEAD)
if [ "$head" != "$SFC_COMMIT" ]; then
  echo "build_superfamiconv: $src is at $head, expected $SFC_COMMIT" >&2
  exit 1
fi
log="$src/build.log"
if ! { cmake -S "$src" -B "$src/build" -DCMAKE_BUILD_TYPE=Release && cmake --build "$src/build" -j"$(nproc)"; } \
    >"$log" 2>&1; then
  tail -n 40 "$log" >&2
  echo "build_superfamiconv: build failed (log: $log)" >&2
  exit 1
fi
install -d "$prefix/bin"
bin=$(find "$src/build" -maxdepth 2 -type f -name superfamiconv -perm -u+x | head -1)
install -m 0755 "$bin" "$prefix/bin/superfamiconv"
echo "$SFC_COMMIT" > "$prefix/SFC_COMMIT"
echo "build_superfamiconv: installed $prefix/bin/superfamiconv ($SFC_COMMIT)"
sha256sum "$prefix/bin/superfamiconv"
