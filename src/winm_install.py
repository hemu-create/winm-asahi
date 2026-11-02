#!/usr/bin/env python3
import argparse
import hashlib
import subprocess
import platform
import shutil
import sys
import urllib.request
from pathlib import Path

TOOLS_MACOS = ["kmutil", "diskutil", "hdiutil", "asr"]
TOOLS_IMAGE = ["wimlib-imagex", "mkfs.ntfs", "ntfs-3g"]


def cmd_check(args: argparse.Namespace) -> int:
    print(f"platform: {platform.system()} {platform.release()} {platform.machine()}")
    print(f"python: {platform.python_version()}")

    tools = TOOLS_MACOS if platform.system() == "Darwin" else TOOLS_IMAGE
    missing = []
    for tool in tools:
        path = shutil.which(tool)
        print(f"{tool}: {path or 'missing'}")
        if path is None:
            missing.append(tool)

    if platform.system() == "Darwin":
        try:
            import subprocess

            model = subprocess.check_output(
                ["sysctl", "-n", "hw.model"], text=True
            ).strip()
            print(f"model: {model}")
        except Exception as exc:
            print(f"model: unknown ({exc})")

    root = Path(args.workdir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(root)
    print(f"workdir: {root}")
    print(f"free: {usage.free // (1024**3)} GiB")
    if usage.free < 64 * 1024**3:
        print("warning: less than 64 GiB free; a Windows install needs more")

    if missing:
        print(f"missing tools: {', '.join(missing)}")
        print("check: completed with warnings")
    else:
        print("check: ok")
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    print("WinM installation plan")
    print("  target: Apple Silicon Mac, base M3 Air (t8122) first")
    print("  boot: m1n1 stage 1 -> m1n1 stage 2 -> b00t -> EDK2 -> Windows")
    print("  disk: APFS resize -> EFI System Partition -> NTFS Windows volume")
    print("  media: official Windows 11 ARM64 ISO or local UUP build")
    print("  drivers: WinM test drivers, test signing during development")
    print("  recovery: remove custom boot object, restore macOS boot policy")
    print()
    print("This command is a dry run. It does not modify disks.")
    return 0


def cmd_download(args: argparse.Namespace) -> int:
    if not args.url.startswith("https://"):
        print("refusing non-HTTPS URL", file=sys.stderr)
        return 1

    output = Path(args.output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()

    with urllib.request.urlopen(args.url) as response, output.open("wb") as handle:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)
            digest.update(chunk)

    actual = digest.hexdigest()
    print(f"downloaded: {output}")
    print(f"sha256: {actual}")
    if args.sha256 and actual.lower() != args.sha256.lower():
        print("sha256 mismatch", file=sys.stderr)
        return 1
    return 0


def find_wims(root: Path) -> list[Path]:
    return sorted(root.rglob("*.wim"))


def cmd_prepare(args: argparse.Namespace) -> int:
    iso = Path(args.iso).expanduser()
    if not iso.exists():
        print(f"ISO not found: {iso}", file=sys.stderr)
        return 1

    output = Path(args.output).expanduser()
    output.mkdir(parents=True, exist_ok=True)
    print(f"ISO: {iso}")
    print(f"output: {output}")

    if shutil.which("7z") is not None:
        try:
            listing = subprocess.check_output(["7z", "l", str(iso)], text=True)
            wims = [line for line in listing.splitlines() if ".wim" in line.lower()]
            print(f"WIM entries found: {len(wims)}")
            for line in wims[:20]:
                print(f"  {line.strip()}")
        except Exception as exc:
            print(f"7z listing failed: {exc}")
    else:
        print("7z is not installed; cannot inspect ISO contents")

    if shutil.which("wimlib-imagex") is not None:
        for wim in find_wims(output):
            print(f"inspecting {wim}")
            try:
                info = subprocess.check_output(
                    ["wimlib-imagex", "info", str(wim)], text=True
                )
                print(info[:1000])
            except Exception as exc:
                print(f"wimlib info failed: {exc}")
    else:
        print("wimlib-imagex is not installed; WIM inspection skipped")

    print("prepare: scaffold only; extraction and patching are not implemented")
    print("next: extract sources/boot.wim and sources/install.wim, then patch WinPE")
    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    iso = Path(args.iso).expanduser()
    if not iso.exists():
        print(f"ISO not found: {iso}", file=sys.stderr)
        return 1
    if shutil.which("7z") is None:
        print("7z is required to inspect ISO contents", file=sys.stderr)
        return 1
    listing = subprocess.check_output(["7z", "l", str(iso)], text=True)
    print(listing)
    return 0


def cmd_unattend(args: argparse.Namespace) -> int:
    output = Path(args.output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    content = """<?xml version="1.0" encoding="utf-8"?>
<unattend xmlns="urn:schemas-microsoft-com:unattend">
  <settings pass="windowsPE">
    <component name="Microsoft-Windows-Setup" processorArchitecture="arm64"
               publicKeyToken="31bf3856ad364e35" language="neutral"
               versionScope="nonSxS" xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State">
      <UserData>
        <AcceptEula>true</AcceptEula>
      </UserData>
    </component>
  </settings>
  <settings pass="oobeSystem">
    <component name="Microsoft-Windows-Shell-Setup" processorArchitecture="arm64"
               publicKeyToken="31bf3856ad364e35" language="neutral"
               versionScope="nonSxS" xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State">
      <OOBE>
        <HideEULAPage>true</HideEULAPage>
        <HideOnlineAccountScreens>true</HideOnlineAccountScreens>
        <SkipMachineOOBE>true</SkipMachineOOBE>
        <SkipUserOOBE>true</SkipUserOOBE>
      </OOBE>
    </component>
  </settings>
</unattend>
"""
    output.write_text(content)
    print(f"wrote {output}")
    print("Note: LabConfig bypass keys must also be written to the boot.wim WinPE registry.")
    return 0


def cmd_testsign(args: argparse.Namespace) -> int:
    if args.state == "on":
        print("bcdedit /set testsigning on")
        print("bcdedit /set nointegritychecks on")
    else:
        print("bcdedit /set testsigning off")
        print("bcdedit /set nointegritychecks off")
    print("These commands are for development only and weaken platform security.")
    return 0


def cmd_bcd(args: argparse.Namespace) -> int:
    print("Create BCD entries from a Windows installation:")
    print("  bcdboot W:\\Windows /s S: /f UEFI")
    print("  bcdedit /store S:\\EFI\\Microsoft\\Boot\\BCD /set {default} testsigning on")
    print("  bcdedit /store S:\\EFI\\Microsoft\\Boot\\BCD /set {default} nointegritychecks on")
    print("Run these inside a disposable Windows VM or WinPE; do not run on the host.")
    return 0


def cmd_install(args: argparse.Namespace) -> int:
    print("install: not implemented", file=sys.stderr)
    print("This command must not modify disks until APFS resize and recovery are tested.", file=sys.stderr)
    return 1


def cmd_uninstall(args: argparse.Namespace) -> int:
    print("uninstall: not implemented", file=sys.stderr)
    print("Planned: remove the custom boot object, delete WinM partitions, restore macOS boot.", file=sys.stderr)
    return 1


def cmd_recovery(args: argparse.Namespace) -> int:
    print("recovery instructions")
    print("1. Boot into macOS recoveryOS.")
    print("2. Remove the m1n1 custom boot object.")
    print("3. Restore the macOS startup disk and security policy.")
    print("4. Keep a second Mac or Apple Configurator available for DFU recovery.")
    return 0


def cmd_fetch_b00t(args: argparse.Namespace) -> int:
    url = args.url or "https://github.com/hemu-create/winm/releases/download/v0.1.0/b00t.img"
    output = Path(args.output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()

    print(f"fetching {url}")
    with urllib.request.urlopen(url) as response, output.open("wb") as handle:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)
            digest.update(chunk)

    actual = digest.hexdigest()
    print(f"saved: {output}")
    print(f"sha256: {actual}")
    if args.sha256 and actual.lower() != args.sha256.lower():
        print("sha256 mismatch", file=sys.stderr)
        return 1
    return 0



def run_command(command: list[str]) -> int:
    try:
        subprocess.run(command, check=True)
        return 0
    except FileNotFoundError:
        print(f"missing command: {command[0]}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(f"command failed: {' '.join(command)} ({exc.returncode})", file=sys.stderr)
        return exc.returncode



def cmd_disks(args: argparse.Namespace) -> int:
    if platform.system() == "Darwin":
        return run_command(["diskutil", "list"])
    return run_command(["lsblk", "-o", "NAME,SIZE,TYPE,MOUNTPOINT,FSTYPE"])


def cmd_guide(args: argparse.Namespace) -> int:
    print("WinM step guide")
    print("===============")
    print()
    print("1. Back up the Mac. Keep a second Mac or Apple Configurator for DFU recovery.")
    print("2. Confirm macOS 13.5 or newer and Apple Silicon (arm64).")
    print("3. Run the curl bootstrap:")
    print("   curl -fsSL https://raw.githubusercontent.com/hemu-create/winm/master/install.sh | sh")
    print("4. Review the detected model, disks, and partition plan.")
    print("5. Confirm the APFS resize and ESP/NTFS partition commands.")
    print("6. Download the b00t image into the work directory.")
    print("7. Install m1n1 stage 1 as the custom boot object.")
    print("8. Prepare Windows 11 ARM64 media with the official ISO or UUP.")
    print("9. Apply the Windows image to the NTFS volume and create BCD entries.")
    print("10. Reboot and select Windows. Use recoveryOS to remove the boot object.")
    print()
    print("Current automation covers checks, partitioning commands, and b00t download.")
    print("Windows media, WIM apply, driver injection, and BCD remain guided steps.")
    return 0


def execute_commands(commands: list[list[str]], label: str) -> int:
    for command in commands:
        print("running: " + " ".join(command))
        result = subprocess.run(command)
        if result.returncode != 0:
            print(f"command failed: {' '.join(command)}", file=sys.stderr)
            return result.returncode
    print(label + " complete")
    return 0


def cmd_interactive(args: argparse.Namespace) -> int:
    print("Welcome to the WinM installer!")
    print()
    print("This wizard prepares an Apple Silicon Mac for Windows 11 ARM64.")
    print("Nothing is changed until you explicitly confirm a step.")
    print()

    cmd_check(args)
    print()
    cmd_disks(args)
    print()

    disk = input("Disk identifier [disk0]: ").strip() or "disk0"
    container = input("macOS APFS container [disk0s2]: ").strip() or "disk0s2"
    windows_size_text = input("Windows size in GiB [128]: ").strip() or "128"
    esp_size_text = input("ESP size in MiB [512]: ").strip() or "512"

    try:
        windows_size = int(windows_size_text)
        esp_size = int(esp_size_text)
    except ValueError:
        print("sizes must be integers", file=sys.stderr)
        return 1

    setattr(args, "disk", disk)
    setattr(args, "container", container)
    setattr(args, "windows_size", windows_size)
    setattr(args, "esp_size", esp_size)
    setattr(args, "execute", False)

    print()
    cmd_partition_plan(args)
    print()

    commands = build_partition_commands(disk, container, windows_size, esp_size)
    print("Commands to run:")
    for command in commands:
        print("  " + " ".join(command))
    print()
    answer = input("Type YES to execute the partition commands: ").strip()
    if answer == "YES":
        result = execute_commands(commands, "partitioning")
        if result != 0:
            return result
    else:
        print("Skipping partitioning.")

    print()
    setattr(args, "url", "")
    setattr(args, "sha256", "43c842959a3bcba6b9ec1b52c6a1413d09f2e9a45997c07a312ee281a8dc6587")
    setattr(args, "output", str(Path(args.workdir).expanduser() / "b00t.img"))
    fetch_result = cmd_fetch_b00t(args)
    if fetch_result != 0:
        return fetch_result

    print()
    cmd_guide(args)
    return 0



def cmd_partition_plan(args: argparse.Namespace) -> int:
    windows_size = getattr(args, "windows_size", 128)
    esp_size = getattr(args, "esp_size", 512)
    print("Partition plan (dry run; review before running):")
    print()
    print("1. Identify the target disk:")
    print("   diskutil list")
    print()
    print("2. Resize the macOS APFS container (example):")
    print("   diskutil apfs resizeContainer disk0s2 250g")
    print()
    print("3. Create an EFI System Partition:")
    print(f"   diskutil addPartition disk0 1 'EFI System Partition' FAT32 WINM_ESP {esp_size}m")
    print()
    print("4. Create a Windows NTFS partition:")
    print(f"   diskutil addPartition disk0 2 'Microsoft Basic Data' NTFS WINM_WINDOWS {windows_size}g")
    print()
    print("5. Format and verify:")
    print("   diskutil info WINM_ESP")
    print("   diskutil info WINM_WINDOWS")
    print()
    print("Replace disk identifiers and sizes with values from 'diskutil list'.")
    print("Never run these commands without a full backup.")
    return 0



def build_partition_commands(disk: str, container: str, windows_size: int, esp_size: int) -> list[list[str]]:
    return [
        ["diskutil", "apfs", "resizeContainer", container, "250g"],
        ["diskutil", "addPartition", disk, "1", "EFI System Partition", "FAT32", "WINM_ESP", f"{esp_size}m"],
        ["diskutil", "addPartition", disk, "2", "Microsoft Basic Data", "NTFS", "WINM_WINDOWS", f"{windows_size}g"],
    ]


def cmd_partition(args: argparse.Namespace) -> int:
    commands = build_partition_commands(args.disk, args.container, args.windows_size, args.esp_size)
    print("Partition commands:")
    for command in commands:
        print("  " + " ".join(command))
    print()
    if not args.execute:
        print("Dry run only. Re-run with --execute after reviewing the commands.")
        return 0

    confirm = input("Type YES to execute the partition commands: ").strip()
    if confirm != "YES":
        print("aborted")
        return 1

    for command in commands:
        print("running: " + " ".join(command))
        result = subprocess.run(command)
        if result.returncode != 0:
            print(f"command failed: {' '.join(command)}", file=sys.stderr)
            return result.returncode
    print("partitioning complete")
    return 0



def cmd_apply_wim(args: argparse.Namespace) -> int:
    wim = Path(args.wim).expanduser()
    target = Path(args.target).expanduser()
    if not wim.exists():
        print(f"WIM not found: {wim}", file=sys.stderr)
        return 1
    if shutil.which("wimlib-imagex") is None:
        print("wimlib-imagex is required", file=sys.stderr)
        return 1

    command = ["wimlib-imagex", "apply", str(wim), str(args.image), str(target)]
    print("command: " + " ".join(command))
    if not args.execute:
        print("dry run only; re-run with --execute")
        return 0

    confirm = input("Type YES to apply the WIM: ").strip()
    if confirm != "YES":
        print("aborted")
        return 1
    target.mkdir(parents=True, exist_ok=True)
    return subprocess.run(command).returncode


def cmd_format_ntfs(args: argparse.Namespace) -> int:
    device = args.device
    command = ["mkfs.ntfs", "-f", "-L", args.label, device]
    print("command: " + " ".join(command))
    if not args.execute:
        print("dry run only; re-run with --execute")
        return 0

    confirm = input(f"Type YES to format {device} as NTFS: ").strip()
    if confirm != "YES":
        print("aborted")
        return 1
    return subprocess.run(command).returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="winm-install")
    parser.add_argument("--workdir", default="winm-work", help="working directory")
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="check host and tools")
    check.set_defaults(func=cmd_check)

    plan = sub.add_parser("plan", help="show a dry-run installation plan")
    plan.set_defaults(func=cmd_plan)

    download = sub.add_parser("download", help="download and verify an ISO")
    download.add_argument("--url", required=True)
    download.add_argument("--sha256", default="")
    download.add_argument("--output", required=True)
    download.set_defaults(func=cmd_download)

    prepare = sub.add_parser("prepare", help="inspect and prepare Windows media")
    prepare.add_argument("--iso", required=True)
    prepare.add_argument("--output", default="winm-work/media")
    prepare.set_defaults(func=cmd_prepare)

    inspect = sub.add_parser("inspect", help="list ISO contents")
    inspect.add_argument("--iso", required=True)
    inspect.set_defaults(func=cmd_inspect)

    unattend = sub.add_parser("unattend", help="generate a minimal unattend.xml")
    unattend.add_argument("--output", required=True)
    unattend.set_defaults(func=cmd_unattend)

    testsign = sub.add_parser("testsign", help="print test-signing BCD commands")
    testsign.add_argument("state", choices=["on", "off"])
    testsign.set_defaults(func=cmd_testsign)

    bcd = sub.add_parser("bcd", help="print BCD creation commands")
    bcd.set_defaults(func=cmd_bcd)

    install = sub.add_parser("install", help="install WinM (not implemented)")
    install.set_defaults(func=cmd_install)

    uninstall = sub.add_parser("uninstall", help="remove WinM (not implemented)")
    uninstall.set_defaults(func=cmd_uninstall)

    recovery = sub.add_parser("recovery", help="show recovery instructions")
    recovery.set_defaults(func=cmd_recovery)

    disks = sub.add_parser("disks", help="list disks and partitions")
    disks.set_defaults(func=cmd_disks)

    interactive = sub.add_parser("interactive", help="run the guided installer wizard")
    interactive.set_defaults(func=cmd_interactive)

    guide = sub.add_parser("guide", help="print the step-by-step guide")
    guide.set_defaults(func=cmd_guide)

    partition = sub.add_parser("partition-plan", help="print an APFS/ESP/NTFS partition plan")
    partition.add_argument("--windows-size", type=int, default=128)
    partition.add_argument("--esp-size", type=int, default=512)
    partition.set_defaults(func=cmd_partition_plan)

    partition = sub.add_parser("partition", help="create WinM partitions")
    partition.add_argument("--disk", default="disk0")
    partition.add_argument("--container", default="disk0s2")
    partition.add_argument("--windows-size", type=int, default=128)
    partition.add_argument("--esp-size", type=int, default=512)
    partition.add_argument("--execute", action="store_true")
    partition.set_defaults(func=cmd_partition)

    apply_wim = sub.add_parser("apply-wim", help="apply a WIM to a target directory")
    apply_wim.add_argument("--wim", required=True)
    apply_wim.add_argument("--image", type=int, default=1)
    apply_wim.add_argument("--target", required=True)
    apply_wim.add_argument("--execute", action="store_true")
    apply_wim.set_defaults(func=cmd_apply_wim)

    format_ntfs = sub.add_parser("format-ntfs", help="format a device as NTFS")
    format_ntfs.add_argument("--device", required=True)
    format_ntfs.add_argument("--label", default="WINM_WINDOWS")
    format_ntfs.add_argument("--execute", action="store_true")
    format_ntfs.set_defaults(func=cmd_format_ntfs)

    fetch = sub.add_parser("fetch-b00t", help="download the b00t image")
    fetch.add_argument("--url", default="")
    fetch.add_argument("--sha256", default="43c842959a3bcba6b9ec1b52c6a1413d09f2e9a45997c07a312ee281a8dc6587")
    fetch.add_argument("--output", default="winm-work/b00t.img")
    fetch.set_defaults(func=cmd_fetch_b00t)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
