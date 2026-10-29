#!/usr/bin/env bash
# Build Mesen 2 from source for the Retrogaze proof harness (headless --testRunner, Linux).
#
#   proof/tools/build_mesen2.sh <mesen2-src-dir> <install-prefix>
#
# <mesen2-src-dir>  checkout of SourMesen/Mesen2 at MESEN2_COMMIT; fetched there (shallow) if the
#                   directory does not exist. Built in place with the upstream makefile.
# <install-prefix>  receives bin/Mesen and MESEN2_COMMIT. bin/Mesen is a framework-dependent .NET 8
#                   single-file app; MesenCore.so, libSkiaSharp.so and libHarfBuzzSharp.so are
#                   embedded and unpacked into Mesen's home dir at every start.
# Idempotent: does nothing when <install-prefix>/MESEN2_COMMIT already names the pinned commit.
# Build needs: git, make, clang++, sdl2-config (libsdl2-dev), zip, .NET SDK 8 (NuGet access).
# Run needs: .NET runtime 8, libsdl2-2.0-0, libx11-6. No display or audio device: --testRunner
# never initialises SDL video, audio or input.
# Mesen 2 is GPL-3.0; it is used here only as a test tool and is not linked or shipped.
set -euo pipefail

MESEN2_REPO=https://github.com/SourMesen/Mesen2.git
MESEN2_COMMIT=b9fa69ddc6d0a331fb103fdb5eef6904305703c2   # master 2026-06-04, archive of 2.1.1

if [ $# -ne 2 ]; then
  echo "usage: $0 <mesen2-src-dir> <install-prefix>" >&2
  exit 2
fi
src=$1
prefix=$2

if [ -x "$prefix/bin/Mesen" ] && [ "$(cat "$prefix/MESEN2_COMMIT" 2>/dev/null)" = "$MESEN2_COMMIT" ]; then
  echo "build_mesen2: $prefix/bin/Mesen is already built from $MESEN2_COMMIT"
  exit 0
fi

for tool in git make clang++ sdl2-config zip dotnet; do
  command -v "$tool" >/dev/null || { echo "build_mesen2: missing tool: $tool" >&2; exit 1; }
done
# Newest installed 8.x SDK. A newer SDK beside it (GitHub's ubuntu-24.04 image ships .NET 10) would win by
# default, so the build pins this one with a global.json in the source dir (below).
sdk8=$(dotnet --list-sdks | awk '$1 ~ /^8\./ { v = $1 } END { print v }')
if [ -z "$sdk8" ]; then
  echo "build_mesen2: need .NET SDK 8.x, found: $(dotnet --list-sdks | awk '{ print $1 }' | tr '\n' ' ')" >&2
  exit 1
fi
case "$(uname -m)" in
  x86_64) platform=linux-x64 ;;
  aarch64) platform=linux-arm64 ;;
  *) echo "build_mesen2: unsupported machine $(uname -m)" >&2; exit 1 ;;
esac

if [ ! -d "$src" ]; then
  git init -q "$src"
  git -C "$src" fetch -q --depth 1 "$MESEN2_REPO" "$MESEN2_COMMIT"
  git -C "$src" checkout -q --detach FETCH_HEAD
fi
head=$(git -C "$src" rev-parse HEAD)
if [ "$head" != "$MESEN2_COMMIT" ]; then
  echo "build_mesen2: $src is at $head, expected $MESEN2_COMMIT" >&2
  exit 1
fi
# Upstream has no global.json at this commit, so this is an untracked file and HEAD is unchanged.
printf '{ "sdk": { "version": "%s", "rollForward": "disable" } }\n' "$sdk8" > "$src/global.json"
if [ "$(cd "$src" && dotnet --version)" != "$sdk8" ]; then
  echo "build_mesen2: could not pin .NET SDK $sdk8 in $src" >&2
  exit 1
fi

export DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1 DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1
# Upstream makefile, default target "ui": the core (clang++ -O3, ThinLTO) -> MesenCore.so, then
# "dotnet publish" twice (Release, -p:OptimizeUi=true, framework-dependent single file).
make -C "$src" -j"$(nproc)"
dotnet build-server shutdown >/dev/null 2>&1 || true   # do not leave a compiler server running

install -d "$prefix/bin"
install -m 0755 "$src/bin/$platform/Release/$platform/publish/Mesen" "$prefix/bin/Mesen"
echo "$MESEN2_COMMIT" > "$prefix/MESEN2_COMMIT"
echo "build_mesen2: installed $prefix/bin/Mesen ($MESEN2_COMMIT)"
sha256sum "$prefix/bin/Mesen"
