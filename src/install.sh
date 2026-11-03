#!/bin/sh
# SPDX-License-Identifier: MIT

set -e

if [ "${0%/*}" != "$0" ]; then
    cd "${0%/*}"
fi

export LC_ALL=en_US.UTF-8
export LANG=en_US.UTF-8
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

if [ ! -e /System ]; then
    echo "The WinM installer must run from macOS."
    echo "It prepares an Apple Silicon Mac for Windows 11 ARM64."
    exit 1
fi

macos_ver=$(/usr/libexec/PlistBuddy -c "Print :ProductVersion" \
    /System/Library/CoreServices/SystemVersion.plist 2>/dev/null || true)

if [ -z "$macos_ver" ]; then
    echo "Unable to determine macOS version."
    exit 1
fi

if [ "${macos_ver%%.*}" -lt 13 ]; then
    echo "This installer requires macOS 13.5 or later."
    exit 1
fi

if ! arch -arm64 ls >/dev/null 2>/dev/null; then
    echo "This is not an Apple Silicon Mac."
    echo "WinM only supports Apple Silicon."
    exit 1
fi

if [ "$(arch)" != "arm64" ]; then
    echo "Switching to ARM64 mode..."
    exec arch -arm64 ./install.sh "$@"
fi

exec </dev/tty >/dev/tty 2>/dev/tty

WORKDIR="${WINM_WORKDIR:-$HOME/winm-work}"
mkdir -p "$WORKDIR"

if [ ! -f "$PWD/main.py" ]; then
    if [ ! -d "$WORKDIR/winm-asahi/src" ]; then
        echo "Cloning WinM installer..."
        git clone --depth 1 https://github.com/hemu-create/winm-asahi.git "$WORKDIR/winm-asahi"
    fi
    cd "$WORKDIR/winm-asahi/src"
fi

export WINM_INSTALL=1
export WINM_WORKDIR="$WORKDIR"

echo
echo "Starting the WinM Windows installer."
echo "Nothing is changed until you explicitly confirm a step."
echo

exec python3 main.py
