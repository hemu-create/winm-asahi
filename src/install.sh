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

LOCAL_INSTALLER="$PWD/winm_install.py"
INSTALLER="$WORKDIR/winm_install.py"
CDN_URL="https://cdn.jsdelivr.net/gh/hemu-create/winm@master/installer/winm_install.py"
RAW_URL="https://raw.githubusercontent.com/hemu-create/winm/master/installer/winm_install.py"

download() {
    curl --fail --silent --show-error --location \
        --connect-timeout 5 --max-time 30 \
        --proto '=https' --tlsv1.2 "$1" -o "$INSTALLER"
}

if [ -f "$LOCAL_INSTALLER" ]; then
    cp "$LOCAL_INSTALLER" "$INSTALLER"
else
    if ! download "$CDN_URL"; then
        echo "CDN download failed; trying raw GitHub..." >&2
        if ! download "$RAW_URL"; then
            echo "curl failed; retrying with Python urllib..." >&2
            python3 - "$RAW_URL" "$INSTALLER" <<'PY'
import sys
import urllib.request

url, output = sys.argv[1], sys.argv[2]
with urllib.request.urlopen(url, timeout=30) as response, open(output, "wb") as handle:
    handle.write(response.read())
PY
        fi
    fi
fi

echo
echo "Starting the WinM Windows installer wizard."
echo "Nothing is changed until you explicitly confirm a step."
echo

exec python3 "$INSTALLER" --workdir "$WORKDIR" interactive