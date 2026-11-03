#!/usr/bin/python3
# SPDX-License-Identifier: MIT
import os, os.path, shlex, subprocess, sys, time, termios, json, getpass, reporting
from dataclasses import dataclass

import system, osenum, stub, diskutil, osinstall, asahi_firmware, m1n1, bugs
from util import *

PART_ALIGN = psize("1MiB")

STUB_SIZE = align_down(psize("2.5GB"), PART_ALIGN)

# Minimum free space to leave when resizing, to allow for OS upgrades
MIN_FREE_OS = psize("38GB")
# Minimum free space to leave for non-OS containers
MIN_FREE = psize("1GB")

# 2.5GB stub + 5GB OS + 0.5GB EFI = 8GB, round up to 10GB
MIN_INSTALL_FREE = psize("10GB")

MIN_MACOS_VERSION = "13.5"
MIN_MACOS_VERSION_EXPERT = "12.3"

@dataclass
class IPSW:
    version: str
    min_macos: str
    min_iboot: str
    min_sfr: str
    expert_only: bool
    devices: list
    url: str

@dataclass
class Device:
    min_ver: str
    expert_only: bool

CHIP_MIN_VER = {
    0x8103: "11.0",     # T8103, M1
    0x6000: "12.0",     # T6000, M1 Pro
    0x6001: "12.0",     # T6001, M1 Max
    0x6002: "12.3",     # T6002, M1 Ultra
    0x8112: "12.4",     # T8112, M2
    0x6020: "13.1",     # T6020, M2 Pro
    0x6021: "13.1",     # T6021, M2 Max
    0x6022: "13.4",     # T6022, M2 Ultra
    0x8122: "14.8.3",   # T8122, M3
    0x6030: "14.8.3",   # T6030, M3 Pro
    0x6031: "14.8.3",   # T6031, M3 Max (16-core)
    0x6034: "14.8.3",   # T6034, M3 Max (14-core)
}

DEVICES = {
    "j274ap":   Device("11.0", False),  # Mac mini (M1, 2020)
    "j293ap":   Device("11.0", False),  # MacBook Pro (13-inch, M1, 2020)
    "j313ap":   Device("11.0", False),  # MacBook Air (M1, 2020)
    "j456ap":   Device("11.3", False),  # iMac (24-inch, M1, 2021)
    "j457ap":   Device("11.3", False),  # iMac (24-inch, M1, 2021)
    "j314cap":  Device("12.0", False),  # MacBook Pro (14-inch, M1 Max, 2021)
    "j314sap":  Device("12.0", False),  # MacBook Pro (14-inch, M1 Pro, 2021)
    "j316cap":  Device("12.0", False),  # MacBook Pro (16-inch, M1 Max, 2021)
    "j316sap":  Device("12.0", False),  # MacBook Pro (16-inch, M1 Pro, 2021)
    "j375cap":  Device("12.3", False),  # Mac Studio (M1 Max, 2022)
    "j375dap":  Device("12.3", False),  # Mac Studio (M1 Ultra, 2022)
    "j413ap":   Device("12.4", False),  # MacBook Air (M2, 2022)
    "j493ap":   Device("12.4", False),  # MacBook Pro (13-inch, M2, 2022)
    "j414cap":  Device("13.2", False),  # MacBook Pro (14-inch, M2 Max, 2023)
    "j414sap":  Device("13.2", False),  # MacBook Pro (14-inch, M2 Pro, 2023)
    "j416cap":  Device("13.2", False),  # MacBook Pro (16-inch, M2 Max, 2023)
    "j416sap":  Device("13.2", False),  # MacBook Pro (16-inch, M2 Pro, 2023)
    "j473ap":   Device("13.2", False),  # Mac mini (M2, 2023)
    "j474sap":  Device("13.2", False),  # Mac mini (M2 Pro, 2023)
    "j415ap":   Device("13.4", False),  # MacBook Air (15-inch, M2, 2023)
    "j475cap":  Device("13.4", False),  # Mac Studio (M2 Max, 2023)
    "j475dap":  Device("13.4", False),  # Mac Studio (M2 Ultra, 2023)
    "j180dap":  Device("13.4", False),  # Mac Pro (M2 Ultra, 2023)
    "j433ap":   Device("14.8.3", False), # iMac (24-inch, M3, 2023)
    "j434ap":   Device("14.8.3", False), # iMac (24-inch, M3, 2023)
    "j504ap":   Device("14.8.3", False), # MacBook Pro (14-inch, M3, 2023)
    "j613ap":   Device("14.8.3", False), # MacBook Air (13-inch, M3, 2024)
    "j615ap":   Device("14.8.3", False), # MacBook Air (15-inch, M3, 2024)
    "j514sap":  Device("14.8.3", False), # MacBook Pro (14-inch, M3 Pro, 2023)
    "j514cap":  Device("14.8.3", False), # MacBook Pro (14-inch, M3 Max, 2023)
    "j514map":  Device("14.8.3", False), # MacBook Pro (14-inch, M3 Max, 2023)
    "j516sap":  Device("14.8.3", False), # MacBook Pro (16-inch, M3 Pro, 2023)
    "j516cap":  Device("14.8.3", False), # MacBook Pro (16-inch, M3 Max, 2023)
    "j516map":  Device("14.8.3", False), # MacBook Pro (16-inch, M3 Max, 2023)
}

# Asahi Linux does not support running in a virtual machine, this option
# exists only for development of the installer itself.
if os.environ.get("ALLOW_VM", None):
    CHIP_MIN_VER[0xfe00] = "12.0"
    DEVICES["vma2macosap"] = Device("12.0", False)

IPSW_VERSIONS = [
    IPSW("12.3.1",
         "12.1",
         "iBoot-7459.101.3",
         "21.5.258.0.0,0",
         False,
         None,
         "https://updates.cdn-apple.com/2022SpringFCS/fullrestores/002-79219/851BEDF0-19DB-4040-B765-0F4089D1530D/UniversalMac_12.3.1_21E258_Restore.ipsw"),
    IPSW("12.3",
         "12.1",
         "iBoot-7459.101.2",
         "21.5.230.0.0,0",
         False,
         None,
         "https://updates.cdn-apple.com/2022SpringFCS/fullrestores/071-08757/74A4F2A1-C747-43F9-A22A-C0AD5FB4ECB6/UniversalMac_12.3_21E230_Restore.ipsw"),
    IPSW("13.5",
         "13.0",
         "iBoot-8422.141.2",
         "22.7.74.0.0,0",
         False,
         None,
         "https://updates.cdn-apple.com/2023SummerFCS/fullrestores/032-69606/D3E05CDF-E105-434C-A4A1-4E3DC7668DD0/UniversalMac_13.5_22G74_Restore.ipsw"),
    IPSW("14.8.3",
         "14.6",
         "iBoot-10151.140.19",
         "23.10.220.0.0,0",
         False,
         ["j433ap", "j434ap", "j504ap", "j613ap", "j615ap", "j514sap", "j514cap", "j514map", "j516sap", "j516cap", "j516map"],
         "https://updates.cdn-apple.com/2025FallFCS/patches/089-71124/49AD260A-D47F-4B5E-A793-30446187196E/com_apple_MobileAsset_MacSoftwareUpdate/f6d1ac9149f6a06401ff87fae5b262c420bfc5f7.zip"),
]

class InstallerMain:
    def __init__(self, version):
        self.version = version
        self.data = json.load(open("installer_data.json"))
        self.credentials_validated = False
        self.expert = False
        self.ipsw = None
        self.osins = None
        self.osi = None
        self.m1n1 = "boot/m1n1.bin"
        self.m1n1_ver = m1n1.get_version(self.m1n1)
        self.sys_disk = None
        self.cur_disk = None

    def input(self):
        self.flush_input()
        return input()

    def get_size(self, prompt, default=None, min=None, max=None, total=None):
        self.flush_input()
        if default is not None:
            prompt += f" ({default})"
        new_size = input_prompt(prompt + f": ").strip()
        try:
            if default is not None and not new_size:
                new_size = default
            if new_size.lower() == "min" and min is not None:
                val = min
            elif new_size.lower() == "max" and max is not None:
                val = max
            elif new_size.endswith("%") and total is not None:
                val = int(float(new_size[:-1]) * total / 100)
            elif new_size.endswith("B"):
                val = psize(new_size.upper())
            else:
                val = psize(new_size.upper() + "B")
        except Exception as e:
            print(e)
            val = None

        if val is None:
            p_error(f"Invalid size '{new_size}'.")

        return val

    def choice(self, prompt, options, default=None):
        is_array = False

        if isinstance(options, list):
            is_array = True
            options = {str(i+1): v for i, v in enumerate(options)}
            if default is not None:
                default += 1

        int_keys = all(isinstance(i, int) for i in options.keys())

        for k, v in options.items():
            p_choice(f"  {col(BRIGHT)}{k}{col(NORMAL)}: {v}")

        if default:
            prompt += f" ({default})"

        while True:
            self.flush_input()
            res = input_prompt(prompt + ": ").strip()
            if res == "" and default is not None:
                res = str(default)
            if res not in options:
                p_warning(f"Enter one of the following: {', '.join(map(str, options.keys()))}")
                continue
            print()
            if is_array:
                return int(res) - 1
            else:
                return res

    def yesno(self, prompt, default=False):
        if default:
            prompt += " (Y/n): "
        else:
            prompt += " (y/N): "

        while True:
            self.flush_input()
            res = input_prompt(prompt).strip()
            if not res:
                return default
            elif res.lower() in ("y", "yes", "1", "true"):
                return True
            elif res.lower() in ("n", "no", "0", "false"):
                return False

            p_warning(f"Please enter 'Y' or 'N'")

    def check_cur_os(self):
        if self.cur_os is None:
            p_error("Unable to determine primary OS.")
            p_error("This installer requires you to already have a macOS install with")
            p_error("at least one administrator user that is a machine owner.")
            p_error("Please run this installer from your main macOS instance or its")
            p_error("paired recovery, or ensure the default boot volume is set correctly.")
            sys.exit(1)

        p_progress(f"Using OS '{self.cur_os.label}' ({self.cur_os.sys_volume}) for machine authentication.")
        logging.info(f"Current OS: {self.cur_os.label} / {self.cur_os.sys_volume}")

        if not self.cur_os.admin_users or self.cur_os.admin_users == ["_mbsetupuser"] or (
            self.sysinfo.boot_mode == "macOS" and self.sysinfo.login_user not in self.cur_os.admin_users):
            # Out of date Preboot partition?
            p_message(f"Oops, your Preboot volume may be out of date. Fixing that for you...")
            p = subprocess.run(["diskutil", "apfs", "updatePreboot", self.cur_os.system], check=True,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT)
            logging.debug(f"process output: {p.stdout}")
            self.cur_os.update_admin_users()
            p_message(f"Preboot volume updated.")

        if not self.cur_os.admin_users or self.cur_os.admin_users == ["_mbsetupuser"]:
            p_error("No admin users found in the primary OS. Cannot continue.")
            p_message("If this is a new or freshly reset machine, you will have to go through macOS")
            p_message("initial user set-up and create an admin user before using this installer.")
            sys.exit(1)

        if self.sysinfo.boot_mode == "macOS" and self.sysinfo.login_user not in self.cur_os.admin_users:
            p_error(f"Your login user {self.sysinfo.login_user} is not a machine admin.")
            print()
            p_info(f"These users are machine admins: {' '.join(self.cur_os.admin_users)}")
            print()
            p_message(f"You have to be a machine admin to install {DISTRO}.")
            sys.exit(1)

    def get_admin_credentials(self):
        if self.credentials_validated:
            return

        print()
        p_message("To continue the installation, you will need to enter your macOS")
        p_message("admin credentials.")
        print()

        if self.sysinfo.boot_mode == "macOS":
            self.admin_user = self.sysinfo.login_user
        else:
            if len(self.cur_os.admin_users) > 1:
                p_question("Choose an admin user for authentication:")
                idx = self.choice("User", self.cur_os.admin_users)
            else:
                idx = 0
            self.admin_user = self.cur_os.admin_users[idx]

        self.admin_password = getpass.getpass(f'Password for {self.admin_user}: ')

    def action_install_into_container(self, avail_parts):
        template = self.choose_os()

        containers = {str(i): p.desc for i,p in enumerate(self.parts) if p in avail_parts}

        print()
        p_question("Choose a container to install into:")
        idx = self.choice("Target container", containers)
        self.part = self.parts[int(idx)]

        ipsw = self.choose_ipsw(template.get("supported_fw", None))
        logging.info(f"Chosen IPSW version: {ipsw.version}")

        self.ins = stub.StubInstaller(self.sysinfo, self.dutil, self.osinfo)
        self.ins.load_ipsw(ipsw)
        self.osins = osinstall.OSInstaller(self.dutil, self.data, template)
        self.osins.load_package()

        self.do_install()

    def action_wipe(self):
        p_warning("This will wipe all data on the currently selected disk.")
        p_warning("Are you sure you want to continue?")
        if not self.yesno("Wipe my disk"):
            return True

        print()

        template = self.choose_os()

        self.osins = osinstall.OSInstaller(self.dutil, self.data, template)
        self.osins.load_package()

        min_size = STUB_SIZE + (self.osins.min_size if self.expert else self.osins.min_recommended_size)
        print()
        p_message(f"Minimum required space for this OS: {ssize(min_size)}")

        start, end = self.dutil.get_disk_usable_range(self.cur_disk)
        os_size = self.get_os_size_and_info(end - start, min_size, template)

        p_progress(f"Partitioning the whole disk ({self.cur_disk})")
        self.part = self.dutil.partitionDisk(self.cur_disk, "apfs", self.osins.name, STUB_SIZE)

        p_progress(f"Creating new stub macOS named {self.osins.name}")
        logging.info(f"Creating stub macOS: {self.osins.name}")
        self.do_install(os_size)

    def action_install_into_free(self, avail_free):
        template = self.choose_os()

        self.osins = osinstall.OSInstaller(self.dutil, self.data, template)
        self.osins.load_package()

        min_size = STUB_SIZE + (self.osins.min_size if self.expert else self.osins.min_recommended_size)
        print()
        p_message(f"Minimum required space for this OS: {ssize(min_size)}")

        frees = {str(i): p.desc for i,p in enumerate(self.parts)
                 if p in avail_free and align_down(p.size, PART_ALIGN) >= min_size}

        if len(frees) < 1:
            p_error( "There is not enough free space to install this OS.")
            print()
            p_message("Press enter to go back to the main menu.")
            self.input()
            return True

        if len(frees) > 1:
            print()
            p_question("Choose a free area to install into:")
            idx = self.choice("Target area", frees)
        else:
            idx = list(frees.keys())[0]
        free_part = self.parts[int(idx)]

        print()
        p_message(f"Available free space: {ssize(free_part.size)}")

        os_size = self.get_os_size_and_info(free_part.size, min_size, template)

        p_progress(f"Creating new stub macOS named {self.osins.name}")
        logging.info(f"Creating stub macOS: {self.osins.name}")
        self.part = self.dutil.addPartition(free_part.name, "apfs", self.osins.name, STUB_SIZE)

        self.do_install(os_size)

    def get_os_size_and_info(self, free_size, min_size, template):
        os_size = None
        if self.osins.expandable:
            print()
            p_question("How much space should be allocated to the new OS?")
            p_message("  You can enter a size such as '1GB', a fraction such as '50%',")
            p_message("  the word 'min' for the smallest allowable size, or")
            p_message("  the word 'max' to use all available space.")
            min_perc = 100 * min_size / free_size
            while True:
                os_size = self.get_size("New OS size", default="max",
                                    min=min_size, max=free_size,
                                    total=free_size)
                if os_size is None:
                    continue
                os_size = align_down(os_size, PART_ALIGN)
                if os_size < min_size:
                    p_error(f"Size is too small, please enter a value > {ssize(min_size)} ({min_perc:.2f}%)")
                    continue
                if os_size > free_size:
                    p_error(f"Size is too large, please enter a value < {ssize(free_size)}")
                    continue
                break

            print()
            p_message(f"The new OS will be allocated {ssize(os_size)} of space,")
            p_message(f"leaving {ssize(free_size - os_size)} of free space.")
            os_size -= STUB_SIZE

        print()
        self.flush_input()
        p_question("Enter a name for your OS")
        label = input_prompt(f"OS name ({self.osins.name}): ") or self.osins.name
        self.osins.name = label
        logging.info(f"New OS name: {label}")
        print()

        ipsw = self.choose_ipsw(template.get("supported_fw", None))
        logging.info(f"Chosen IPSW version: {ipsw.version}")
        self.ins = stub.StubInstaller(self.sysinfo, self.dutil, self.osinfo)
        self.ins.load_ipsw(ipsw)
        return os_size

    def action_repair_or_upgrade(self, oses, upgrade):
        choices = {str(i): f"{p.desc}\n      {str(o)}" for i, (p, o) in enumerate(oses)}

        if len(choices) > 1:
            print()
            if upgrade:
                p_question("Choose an existing install to upgrade:")
            else:
                p_question("Choose an incomplete install to repair:")
            idx = self.choice("Installed OS", choices)
        else:
            idx = list(choices.keys())[0]

        self.part, osi = oses[int(idx)]

        if upgrade:
            p_progress(f"Upgrading installation {self.part.name} ({self.part.label})")
            p_info(f"  Old m1n1 stage 1 version: {osi.m1n1_ver}")
            p_info(f"  New m1n1 stage 1 version: {self.m1n1_ver}")
            print()
        else:
            p_progress(f"Resuming installation into {self.part.name} ({self.part.label})")

        self.ins = stub.StubInstaller(self.sysinfo, self.dutil, self.osinfo)
        if not self.ins.check_existing_install(osi):
            op = "upgrade" if upgrade else "repair"
            p_error(   "The existing installation is missing files.")
            p_message(f"This tool can only {op} installations that completed the first")
            p_message( "stage of the installation process. If it was interrupted, please")
            p_message( "delete the partitions manually and reinstall from scratch.")
            return False

        self.dutil.remount_rw(self.ins.osi.system)
        self.ins.repair(self.cur_os)

        if upgrade:
            # Note: we get the vars out of the boot.bin in the system volume instead of the
            # actual installed fuOS. This is arguably the better option, since it allows
            # users to fix their install using this functionality if they messed up the boot
            # object.
            vars = m1n1.extract_vars(self.ins.boot_obj_path)
            if vars is None:
                p_error("Could not get variables from the installed m1n1")
                p_message(f"Path: {self.ins.boot_obj_path}")
                return False

            p_progress(f"Transferring m1n1 variables:")
            for v in vars:
                p_info(f"  {v}")

            print()
            m1n1.build(self.m1n1, self.ins.boot_obj_path, vars)

        # Unhide the SystemVersion, if hidden
        self.ins.prepare_for_bless()

        # Go for step2 again
        self.step2()

    def action_set_vol_bootable(self, oses):
        choices = {str(i): f"{p.desc}\n      {str(o)}" for i, (p, o) in enumerate(oses)}

        if len(choices) > 1:
            print()
            p_question("Choose an install to fix macOS 27 compatibility on:")
            idx = self.choice("Installed OS", choices)
        else:
            idx = list(choices.keys())[0]

        self.part, osi = oses[int(idx)]

        self.dutil.remount_rw(osi.system)
        fsctl_set_bootable(osi.system, True)
        print()
        p_success(f"macOS 27 fix applied. System Settings caches the bootability state,")
        p_success(f"so you may need to reboot before the os becomes visible")
        p_success(f"Press enter to continue.")
        self.input()
        print()

        return True

    def action_rebuild_vendorfw(self, oses):
        choices = {str(i): f"{p.desc}\n      {str(o)}" for i, (p, o) in enumerate(oses)}

        if len(choices) > 1:
            print()
            p_question("Choose an install to rebuild firmware for:")
            idx = self.choice("Installed OS", choices)
        else:
            idx = list(choices.keys())[0]

        self.part, osi = oses[int(idx)]
        self.ins = stub.StubInstaller(self.sysinfo, self.dutil, self.osinfo)
        if not self.ins.check_existing_install(osi):
            p_error(   "The existing installation is missing files.")
            p_message(f"This tool can only rebuild firmware on installations that completed the first")
            p_message( "stage of the installation process. If it was interrupted, please")
            p_message( "delete the partitions manually and reinstall from scratch.")
            return False

        vars = m1n1.extract_vars(self.ins.boot_obj_path)
        if vars is None:
            p_error("Could not get variables from the installed m1n1")
            p_message(f"Path: {self.ins.boot_obj_path}")
            return False

        esp_id = None
        for var in vars:
            k, v = var.split('=')
            if k == "chosen.asahi,efi-system-partition":
                esp_id = v
                break
        if esp_id is None:
            p_error("Unable to determine the associated EFI system partition for this install.")
            p_message("Is first stage m1n1 corrupted?")
            return False

        target = self.dutil.get_partition_info(esp_id)
        mountpoint = self.dutil.mount(target.name)

        os.makedirs("vendorfw", exist_ok=True)
        fw_pkg = asahi_firmware.core.FWPackage("vendorfw")
        ipsw = None
        for ver in IPSW_VERSIONS:
            if ver.version == osi.version:
                ipsw = ver
                break
        if ipsw is None:
            p_error(f"This install is using an unsupported macOS version {osi.version}")
            p_message("Unable to rebuild firmware")
            return False

        self.ins.load_ipsw(ipsw)
        self.ins.load_identity()
        self.ins.collect_firmware(fw_pkg)
        fw_pkg.close()

        p_plain(f"  Copying firmware into {target.name} partition...")
        base = os.path.join(mountpoint, "vendorfw")
        logging.info(f"Firmware -> {base}")
        shutil.copytree(fw_pkg.path, base, dirs_exist_ok=True)
        asahi = os.path.join(mountpoint, "asahi")
        all_fw = "all_firmware.tar.gz"
        shutil.copy(all_fw, os.path.join(asahi, all_fw))

        print()
        p_success(f"Firmware rebuild complete. Press enter to continue.")
        self.input()
        print()

        return True

    def do_install(self, total_size=None):
        p_progress(f"Installing stub macOS into {self.part.name} ({self.part.label})")

        self.ins.prepare_volume(self.part)
        self.ins.check_volume()
        self.ins.install_files(self.cur_os)

        self.osins.partition_disk(self.part.name, total_size)

        pkg = None
        if self.osins.needs_firmware:
            os.makedirs("vendorfw", exist_ok=True)
            pkg = asahi_firmware.core.FWPackage("vendorfw")
            self.ins.collect_firmware(pkg)
            pkg.close()
            self.osins.firmware_package = pkg

        self.osins.install(self.ins)

        for i in self.osins.idata_targets:
            self.ins.collect_installer_data(i)
            shutil.copy("installer.log", os.path.join(i, "installer.log"))

        self.step2(report=True)

    def choose_ipsw(self, supported_fw=None):
        sys_iboot = split_ver(self.sysinfo.sys_firmware)
        sys_macos = split_ver(self.sysinfo.macos_ver)
        sys_sfr = split_ver(self.sysinfo.sfr_full_ver)
        chip_min = split_ver(CHIP_MIN_VER.get(self.sysinfo.chip_id, "0"))
        device_min = split_ver(self.device.min_ver)
        minver = [ipsw for ipsw in IPSW_VERSIONS
                 if split_ver(ipsw.version) >= max(chip_min, device_min)
                 and (supported_fw is None or ipsw.version in supported_fw)
                 and (ipsw.devices is None or self.sysinfo.device_class in ipsw.devices)]
        avail = [ipsw for ipsw in minver
                 if split_ver(ipsw.min_iboot) <= sys_iboot
                 and split_ver(ipsw.min_macos) <= sys_macos
                 and split_ver(ipsw.min_sfr) <= sys_sfr
                 and (not ipsw.expert_only or self.expert)]

        minver.sort(key=lambda ipsw: split_ver(ipsw.version))

        if not avail:
            p_error("Your system firmware is too old.")
            p_error(f"Please upgrade to macOS {minver[0].version} or newer.")
            sys.exit(1)

        if self.expert:
            p_question("Choose the macOS version to use for boot firmware:")
            p_plain("(If unsure, just press enter)")
            p_warning("Picking a non-default option here is UNSUPPORTED and will BREAK YOUR SYSTEM.")
            p_warning("DO NOT FILE BUGS. YOU HAVE BEEN WARNED.")
            idx = self.choice("Version", [i.version for i in avail], len(avail)-1)
        else:
            idx = len(avail)-1

        self.ipsw = ipsw = avail[idx]
        p_message(f"Using macOS {ipsw.version} for OS firmware")
        print()

        return ipsw

    def choose_os(self):
        os_list = self.data["os_list"]
        if not self.expert:
            os_list = [i for i in os_list if not i.get("expert", False)]
        if self.cur_disk != self.sys_disk:
            os_list = [i for i in os_list if i.get("external_boot", False)]
        p_question("Choose an OS to install:")
        idx = self.choice("OS", [i["name"] for i in os_list])
        os = os_list[idx]
        logging.info(f"Chosen OS: {os['name']}")
        return os

    def set_reduced_security(self):
        while True:
            self.get_admin_credentials()
            print()
            p_progress("Preparing the new OS for booting in Reduced Security mode...")
            try:
                subprocess.run(["bputil", "-g", "-v", self.ins.osi.vgid,
                                "-u", self.admin_user, "-p", self.admin_password], check=True)
                break
            except subprocess.CalledProcessError:
                p_error("Failed to run bputil. Press enter to try again.")
                self.input()

        self.credentials_validated = True
        print()

    def bless(self):
        while True:
            self.get_admin_credentials()
            print()
            p_progress("Setting the new OS as the default boot volume...")
            try:
                subprocess.run(["bless", "--setBoot",
                                "--device", "/dev/" + self.ins.osi.sys_volume,
                                "--user", self.admin_user, "--stdinpass"],
                               input=self.admin_password.encode("utf-8"),
                               check=True)
                break
            except subprocess.CalledProcessError:
                if self.admin_password.strip() != self.admin_password:
                    p_warning("Failed to run bless.")
                    p_warning("This is probably because your password starts or ends with a space,")
                    p_warning("and that doesn't work due to a silly Apple bug.")
                    p_warning("Let's try a different way. Sorry, you'll have to type it in again.")
                    try:
                        subprocess.run(["bless", "--setBoot",
                                        "--device", "/dev/" + self.ins.osi.sys_volume,
                                        "--user", self.admin_user], check=True)
                        print()
                        return
                    except subprocess.CalledProcessError:
                        pass
                p_error("Failed to run bless. Press enter to try again.")
                self.input()

        self.credentials_validated = True
        print()

    def step2(self, report=False):
        is_1tr = self.sysinfo.boot_mode == "one true recoveryOS"
        is_recovery = "recoveryOS" in self.sysinfo.boot_mode
        sys_ver = split_ver(self.sysinfo.macos_ver)
        if is_1tr and self.ins.osi.paired:
            subprocess.run([self.ins.step2_sh], check=True)
            self.bless()
            self.step2_completed(report)
        elif is_recovery:
            self.set_reduced_security()
            self.bless()
            self.step2_indirect(report)
        else:
            self.bless()
            self.step2_indirect(report)

    def flush_input(self):
        try:
            termios.tcflush(sys.stdin, termios.TCIFLUSH)
        except:
            pass

    def install_info(self, report):
        # Hide the new volume until step2 is done
        self.ins.prepare_for_step2()

        p_success( "Installation successful!")
        print()
        p_progress("Install information:")
        p_info(   f"  APFS VGID: {col()}{self.ins.osi.vgid}")
        if self.osins and self.osins.efi_part:
            p_info(f"  EFI PARTUUID: {col()}{self.osins.efi_part.uuid.lower()}")
        print()

        if report:
            reporting.report(self)

    def step2_completed(self, report=False):
        self.install_info(report)

        print()
        time.sleep(2)
        p_prompt( "Press enter to reboot the system.")
        self.input()
        time.sleep(1)
        os.system("shutdown -r now")

    def step2_indirect(self, report=False):
        # Hide the new volume until step2 is done
        self.ins.prepare_for_step2()

        self.install_info(report)

        p_message( "To be able to boot your new OS, you will need to complete one more step.")
        p_warning( "Please read the following instructions carefully. Failure to do so")
        p_warning( "will leave your new installation in an unbootable state.")
        print()
        p_question( "Press enter to continue.")
        self.input()
        print()
        print()
        print()
        p_message( "When the system shuts down, follow these steps:")
        print()
        p_message( "1. Wait 25 seconds for the system to fully shut down.")
        p_message(f"2. Press and {col(BRIGHT, YELLOW)}hold{col()}{col(BRIGHT)} down the power button to power on the system.")
        p_warning( "   * It is important that the system be fully powered off before this step,")
        p_warning( "     and that you press and hold down the button once, not multiple times.")
        p_warning( "     This is required to put the machine into the right mode.")
        p_message( "3. Release it once you see 'Loading startup options...' or a spinner.")
        p_message( "4. Wait for the volume list to appear.")
        p_message(f"5. Choose '{self.part.label}'.")
        p_message( "6. You will briefly see a 'macOS Recovery' dialog.")
        p_plain(   "   * If you are asked to 'Select a volume to recover',")
        p_plain(   "     then choose your normal macOS volume and click Next.")
        p_plain(   "     You may need to authenticate yourself with your macOS credentials.")
        p_message(f"7. Once the '{DISTRO} installer' screen appears, follow the prompts.")
        print()
        p_warning( "If you end up in a bootloop or get a message telling you that macOS needs to")
        p_warning( "be reinstalled, that means you didn't follow the steps above properly.")
        p_message( "Fully shut down your system without doing anything, and try again.")
        p_message( "If in trouble, hold down the power button to boot, select macOS, run")
        p_message( "this installer again, and choose the 'p' option to retry the process.")
        print()
        time.sleep(2)
        p_prompt( "Press enter to shut down the system.")
        self.input()
        time.sleep(1)
        os.system("shutdown -h now")

    def get_min_free_space(self, p):
        if p.os and any(os.version for os in p.os) and not self.expert and not self.is_edu_128gb:
            logging.info("  Has OS")
            return MIN_FREE_OS
        else:
            return MIN_FREE

    def can_resize(self, p):
        logging.info(f"Checking resizability of {p.name}")
        if p.type != "Apple_APFS":
            logging.info(f"  Not APFS or system container")
            return False

        if p.container is None:
            logging.info(f"  No container?")
            return False

        min_space = self.get_min_free_space(p) + psize("500MB")
        logging.info(f"  Min space required: {min_space}")

        free = p.container["CapacityFree"]
        logging.info(f"  Free space: {free}")
        if free <= min_space:
            logging.info(f"  Cannot resize")
            return False
        else:
            logging.info(f"  Can resize")
            return True

    def action_resize(self, resizable):
        choices = {str(i): p.desc for i,p in enumerate(self.parts) if p in resizable}

        print()
        if len(resizable) > 1 or self.expert:
            p_question("Choose an existing partition to resize:")
            idx = self.choice("Partition", choices)
            target = self.parts[int(idx)]
        else:
            target = resizable[0]

        limits = self.dutil.get_resize_limits(target.name)

        total = target.container["CapacityCeiling"]
        free = target.container["CapacityFree"]
        min_free = self.get_min_free_space(target)
        # Minimum size, ignoring APFS snapshots & co, but with a conservative buffer
        min_size_raw = align_up(total - free + min_free, PART_ALIGN)
        # Minimum size reported by diskutil, considering APFS snapshots & co but with a less conservative buffer
        min_size_safe = limits["MinimumSizePreferred"]
        min_size = max(min_size_raw, min_size_safe)
        overhead = min_size - min_size_raw
        avail = total - min_size

        min_perc = 100 * min_size / total

        assert free > min_free

        p_message( "We're going to resize this partition:")
        p_message(f"  {target.desc}")
        p_info(   f"  Total size: {col()}{ssize(total)}")
        p_info(   f"  Free space: {col()}{ssize(free)}")
        p_info(   f"  Available space: {col()}{ssize(avail)}")
        p_info(   f"  Overhead: {col()}{ssize(overhead)}")
        p_info(   f"  Minimum new size: {col()}{ssize(min_size)} ({min_perc:.2f}%)")
        print()
        if overhead > 16_000_000_000:
            p_warning("  Warning: The selected partition has a large amount of overhead space.")
            p_warning("  This prevents you from resizing the partition to a smaller size, even")
            p_warning("  though macOS reports that space as free.")
            print()
            p_message("  This is usually caused by APFS snapshots used by Time Machine, which")
            p_message("  use up free disk space and block resizing the partition to a smaller")
            p_message("  size. It can also be caused by having a pending macOS upgrade.")
            print()
            p_message("  If you want to resize your partition to a smaller size, please complete")
            p_message("  any pending macOS upgrades and visit this link to learn how to manually")
            p_message("  delete Time Machine snapshots:")
            print()
            p_plain( f"    {col(BLUE, BRIGHT)}https://alx.sh/tmcleanup{col()}")
            print()

            if avail < 2 * PART_ALIGN:
                p_error("  Not enough available space to resize. Please follow the instructions")
                p_error("  above to continue.")
                return False

            if not self.yesno("Continue anyway?"):
                return False
            print()

        if avail < 2 * PART_ALIGN:
            p_error("Not enough available space to resize.")
            return False

        p_question("Enter the new size for your existing partition:")
        p_message( "  You can enter a size such as '1GB', a fraction such as '50%',")
        p_message( "  or the word 'min' for the smallest allowable size.")
        print()
        p_message( "  Examples:")
        p_message( "  30%  - 30% to macOS, 70% to the new OS")
        p_message( "  80GB - 80GB to macOS, the rest to your new OS")
        p_message( "  min  - Shrink macOS as much as (safely) possible")
        print()

        default = "50%"
        if total / 2 < min_size:
            default = "min"
        while True:
            val = self.get_size("New size", default=default, min=min_size, total=total)
            if val is None:
                continue
            val = align_up(val, PART_ALIGN)
            if val < min_size:
                p_error(f"Size is too small, please enter a value > {ssize(min_size)} ({min_perc:.2f}%)")
                continue
            if val >= total:
                p_error(f"Size is too large, please enter a value < {ssize(total)}")
                continue
            freeing = total - val
            print()
            p_message(f"Resizing will free up {ssize(freeing)} of space.")
            if freeing <= MIN_INSTALL_FREE:
                if not self.expert:
                    p_error(f"That's not enough free space for an OS install.")
                    continue
                else:
                    p_warning(f"That's not enough free space for an OS install.")
            print()
            p_message("Note: your system may appear to freeze during the resize.")
            p_message("This is normal, just wait until the process completes.")
            if self.yesno("Continue?"):
                break

        print()
        try:
            self.dutil.resizeContainer(target.name, val)
        except subprocess.CalledProcessError as e:
            print()
            p_error(f"Resize failed. This is usually caused by pre-existing APFS filesystem corruption.")
            p_warning("Carefully read the diskutil logs above for more information about the cause.")
            p_warning("This can usually be solved by doing a First Aid repair from Disk Utility in Recovery Mode.")
            return False

        print()
        p_success(f"Resize complete. Press enter to continue.")
        self.input()
        print()

        return True

    def action_select_disk(self):
        choices = {"1": "Internal storage"}

        for i, disk in enumerate(self.external_disks):
            choices[str(i + 2)] = f"{disk['IORegistryEntryName']} ({ssize(disk['Size'])})"

        print()
        p_question("Choose a disk:")
        idx = int(self.choice("Disk", choices))
        if idx == 1:
            self.cur_disk = self.sys_disk
        else:
            self.cur_disk = self.external_disks[idx - 2]["DeviceIdentifier"]

        return True

    def main(self):
        print()
        p_message(f"Welcome to the {DISTRO} installer!")
        print()
        p_message("This installer will guide you through the process of setting up")
        p_message(f"{DISTRO} on your Mac.")
        print()
        p_message("Please make sure you are familiar with our documentation at:")
        p_plain( f"  {col(BLUE, BRIGHT)}{DISTRO_DOCS}{col()}")
        print()
        p_question("Press enter to continue.")
        self.input()
        print()

        self.expert = False
        if os.environ.get("EXPERT", None):
            p_message("By default, this installer will hide certain advanced options that")
            p_message("are only useful for Asahi Linux developers. You can enable expert mode")
            p_message("to show them. Do not enable this unless you know what you are doing.")
            p_message("Please do not file bugs if things go wrong in expert mode.")
            self.expert = self.yesno("Enable expert mode?")
            print()

        p_progress("Collecting system information...")
        self.sysinfo = system.SystemInfo()
        self.sysinfo.show()
        print()

        bugs.run_checks(self)

        self.chip_min_ver = CHIP_MIN_VER.get(self.sysinfo.chip_id, None)
        self.device = DEVICES.get(self.sysinfo.device_class, None)
        if not self.chip_min_ver or not self.device or (self.device.expert_only and not self.expert):
            p_error("This device is not supported yet!")
            p_error("Please check out the Asahi Linux Blog for updates on device support:")
            print()
            p_error("   https://asahilinux.org/blog/")
            print()
            sys.exit(1)

        if self.sysinfo.boot_mode == "macOS" and (
            (not self.sysinfo.login_user)
            or self.sysinfo.login_user == "unknown"):
            p_error("Could not detect logged in user.")
            p_error("Perhaps you are running this installer over SSH?")
            p_error("Please make sure a user is logged into the local console.")
            p_error("You can use SSH as long as there is a local login session.")
            sys.exit(1)

        if self.expert:
            min_ver = MIN_MACOS_VERSION_EXPERT
        else:
            min_ver = MIN_MACOS_VERSION

        if split_ver(self.sysinfo.macos_ver) < split_ver(min_ver):
            p_error("Your macOS version is too old.")
            p_error(f"Please upgrade to macOS {min_ver} or newer.")
            sys.exit(1)

        while self.main_loop():
            pass

    def main_loop(self):
        p_progress("Collecting partition information...")
        self.dutil = diskutil.DiskUtil()
        self.dutil.get_info()
        if self.sys_disk is None:
            self.cur_disk = self.sys_disk = self.dutil.find_system_disk()

        p_info(f"  System disk: {col()}{self.sys_disk}")

        if self.expert:
            self.external_disks = self.dutil.find_external_disks()
        else:
            self.external_disks = None

        if self.external_disks:
            p_info(f"  Found {len(self.external_disks)} external disk(s)")

        self.parts = self.dutil.get_partitions(self.cur_disk)
        print()

        p_progress("Collecting OS information...")
        self.osinfo = osenum.OSEnum(self.sysinfo, self.dutil, self.cur_disk)
        self.osinfo.collect(self.parts)
        self.is_edu_128gb = self.dutil.get_disk_size(self.sys_disk) < 150 * 1024 * 1024 * 1024
        if self.is_edu_128gb:
            p_warning("Education-only 128GB device detected, allowing to resize macOS below safe limits")
            p_warning("System updates may fail if less than ~30GB of free space remains on the main partition")


        parts_free = []
        parts_empty_apfs = []
        parts_resizable = []
        oses_incomplete = []
        oses_non_vol_boot = []
        oses_upgradable = []
        oses_vendorfw = []

        for i, p in enumerate(self.parts):
            p.index = i
            if p.type in ("Apple_APFS_ISC",):
                continue
            if p.free:
                p.desc = f"(free space: {ssize(p.size)})"
                if p.size >= STUB_SIZE:
                    parts_free.append(p)
            elif p.type.startswith("Apple_APFS"):
                p.desc = "APFS"
                if p.type == "Apple_APFS_Recovery":
                    p.desc += " (System Recovery)"
                if p.label is not None:
                    p.desc += f" [{p.label}]"
                if p.container is None:
                    p.desc += f" (not a container)"
                else:
                    vols = p.container["Volumes"]
                    p.desc += f" ({ssize(p.size)}, {len(vols)} volume{'s' if len(vols) != 1 else ''})"
                    if self.can_resize(p):
                        parts_resizable.append(p)
                    else:
                        if p.size >= STUB_SIZE * 0.95:
                            parts_empty_apfs.append(p)
            else:
                p.desc = f"{p.type} ({ssize(p.size)})"

        print()
        if self.cur_disk == self.sys_disk:
            t = "system"
        else:
            t = "external"
        p_message(f"Partitions in {t} disk ({self.cur_disk}):")

        if self.cur_disk == self.sys_disk:
            self.cur_os = None
        self.is_sfr_recovery = self.sysinfo.boot_vgid in (osenum.UUID_SROS, osenum.UUID_FROS)
        default_os = None

        r = col(YELLOW) + "R" + col()
        b = col(GREEN) + "B" + col()
        u = col(RED) + "?" + col()
        d = col(BRIGHT) + "*" + col()

        is_gpt = self.dutil.disks[self.cur_disk]["Content"] == "GUID_partition_scheme"

        for i, p in enumerate(self.parts):
            if p.desc is None:
                continue
            p_choice(f"  {col(BRIGHT)}{i}{col()}: {p.desc}")
            if not p.os:
                continue
            for os in p.os:
                if not os.version:
                    continue
                state = " "
                if self.sysinfo.boot_vgid == os.vgid and self.sysinfo.boot_uuid == os.rec_vgid:
                    if p.type == "APFS":
                        self.cur_os = os
                    state = r
                elif self.sysinfo.boot_uuid == os.vgid:
                    self.cur_os = os
                    state = b
                elif self.sysinfo.boot_vgid == os.vgid:
                    state = u
                if self.sysinfo.default_boot == os.vgid:
                    default_os = os
                    state += d
                else:
                    state += " "
                p_plain(f"    OS: [{state}] {os}")
                if os.attached_partitions:
                    p_plain(f"      Extra partitions: {' '.join('#' + str(i.index) for i in os.attached_partitions)}")
                if os.stub and os.m1n1_ver:
                    oses_vendorfw.append((p, os))
                if os.stub and not os.sys_vol_bootable:
                    oses_non_vol_boot.append((p, os))
                if os.stub and os.m1n1_ver and os.m1n1_ver != self.m1n1_ver:
                    oses_upgradable.append((p, os))
                elif os.stub and not (os.bp and os.bp.get("coih", None)):
                    oses_incomplete.append((p, os))

        print()
        p_plain(f"  [{b} ] = Booted OS, [{r} ] = Booted recovery, [{u} ] = Unknown")
        p_plain(f"  [ {d}] = Default boot volume")
        print()

        if self.cur_os is None and self.sysinfo.boot_mode != "macOS":
            self.cur_os = default_os
        self.check_cur_os()

        actions = {}

        default = None
        if oses_incomplete:
            actions["p"] = "Repair an incomplete installation"
            default = default or "p"
        if parts_free and is_gpt:
            actions["f"] = "Install an OS into free space"
            default = default or "f"
        if parts_empty_apfs and is_gpt and False: # This feature is confusing, disable it for now
            actions["a"] = "Install an OS into an existing APFS container"
        if parts_resizable and is_gpt:
            actions["r"] = "Resize an existing partition to make space for a new OS"
            default = default or "r"
        if self.cur_disk != self.sys_disk:
            actions["w"] = "Wipe and install into the whole disk"
            # Never make this default!
        if self.external_disks:
            actions["d"] = "Select another disk for installation"
            default = default or "d"
        if oses_upgradable:
            actions["m"] = "Upgrade m1n1 on an existing OS"
            default = default or "m"
        if oses_vendorfw:
            actions["v"] = "Rebuild vendor firmware package"
            default = default or "v"
        if oses_non_vol_boot:
            actions["7"] = "Fix macOS 27 boot picker compatibility"
            default = default or "7"

        if not actions:
            p_error("No actions available on this system.")
            p_message("No partitions have enough free space to be resized, and there is")
            p_message("nothing else to be done.")
            sys.exit(1)

        actions["q"] = "Quit without doing anything"
        default = default or "q"

        print()
        p_question("Choose what to do:")
        act = self.choice("Action", actions, default)

        if act == "f":
            return self.action_install_into_free(parts_free)
        elif act == "a":
            return self.action_install_into_container(parts_empty_apfs)
        elif act == "r":
            return self.action_resize(parts_resizable)
        elif act == "m":
            return self.action_repair_or_upgrade(oses_upgradable, upgrade=True)
        elif act == "p":
            return self.action_repair_or_upgrade(oses_incomplete, upgrade=False)
        elif act == "d":
            return self.action_select_disk()
        elif act == "w":
            return self.action_wipe()
        elif act == "v":
            return self.action_rebuild_vendorfw(oses_vendorfw)
        elif act == "7":
            return self.action_set_vol_bootable(oses_non_vol_boot)
        elif act == "q":
            return False

if __name__ == "__main__":
    if os.environ.get("WINM_INSTALL"):
        workdir = os.environ.get("WINM_WORKDIR", os.path.expanduser("~/winm-work"))
        sys.argv = ["winm-install", "--workdir", workdir, "interactive"]
        raise SystemExit(main())

    logging.basicConfig(level=logging.DEBUG,
                        format='%(asctime)s %(name)-12s %(levelname)-8s %(message)s',
                        datefmt='%m-%d %H:%M',
                        filename='installer.log',
                        filemode='w')

    console = logging.StreamHandler()
    console.setLevel(logging.ERROR)
    formatter = logging.Formatter('%(name)-12s: %(levelname)-8s %(message)s')
    console.setFormatter(formatter)
    logging.getLogger('').addHandler(console)
    logging.info("Startup")

    logging.info("Environment:")
    for var in ("INSTALLER_BASE", "INSTALLER_DATA", "REPO_BASE", "IPSW_BASE", "EXPERT", "REPORT", "REPORT_TAG"):
        logging.info(f"  {var}={os.environ.get(var, None)}")

    try:
        installer_version = open("version.tag", "r").read().strip()
        logging.info(f"Version: {installer_version}")
        InstallerMain(installer_version).main()
    except KeyboardInterrupt:
        print()
        logging.info("KeyboardInterrupt")
        p_error("Interrupted")
    except subprocess.CalledProcessError as e:
        cmd = shlex.join(e.cmd)
        p_error(f"Failed to run process: {cmd}")
        if e.output is not None:
            p_error(f"Output: {e.output}")
        logging.exception("Process execution failed")
        p_warning("If you need to file a bug report, please attach the log file:")
        p_warning(f"  {os.getcwd()}/installer.log")
    except Exception:
        logging.exception("Exception caught")
        p_warning("If you need to file a bug report, please attach the log file:")
        p_warning(f"  {os.getcwd()}/installer.log")

# Integrated WinM Windows installer (replaces the former winm_install.py module)
import argparse
import hashlib
import subprocess
import platform
import shutil
import sys
import urllib.request
import plistlib
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


def disk_total_size_bytes(disk: str) -> int:
    output = subprocess.check_output(
        ["diskutil", "info", "-plist", disk], text=False
    )
    info = plistlib.loads(output)
    for key in ("TotalSize", "Size"):
        if key in info:
            return int(info[key])
    raise RuntimeError(f"could not determine size of {disk}")


def confirm(prompt: str, default: bool = False) -> bool:
    suffix = " (Y/n): " if default else " (y/N): "
    while True:
        response = input(prompt + suffix).strip().lower()
        if not response:
            return default
        if response in ("y", "yes"):
            return True
        if response in ("n", "no"):
            return False
        print("Please answer y or n.")


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

    if windows_size < 62:
        print("Windows size must be at least 62 GiB", file=sys.stderr)
        return 1
    if esp_size < 256:
        print("ESP size must be at least 256 MiB", file=sys.stderr)
        return 1

    try:
        total_size = disk_total_size_bytes(disk)
    except Exception as exc:
        print(f"could not inspect {disk}: {exc}", file=sys.stderr)
        return 1

    windows_bytes = windows_size * 1024**3
    esp_bytes = esp_size * 1024**2
    overhead_bytes = 2 * 1024**3
    macos_size = total_size - windows_bytes - esp_bytes - overhead_bytes
    macos_size = (macos_size // (1024**3)) * (1024**3)
    if macos_size < 64 * 1024**3:
        print("not enough space for a 62 GiB Windows install", file=sys.stderr)
        return 1

    setattr(args, "disk", disk)
    setattr(args, "container", container)
    setattr(args, "windows_size", windows_size)
    setattr(args, "esp_size", esp_size)
    setattr(args, "macos_size", macos_size)
    setattr(args, "execute", False)

    print()
    print(f"Total disk size: {total_size // (1024**3)} GiB")
    print(f"macOS container will be resized to: {macos_size // (1024**3)} GiB")
    print(f"Windows partition: {windows_size} GiB")
    print(f"ESP: {esp_size} MiB")
    print()
    cmd_partition_plan(args)
    print()

    commands = build_partition_commands(disk, container, macos_size, esp_size, windows_size)
    print("Commands to run:")
    for command in commands:
        print("  " + " ".join(command))
    print()
    print("These commands resize macOS and create WinM partitions. They do not delete existing partitions.")
    if confirm("Execute the partition commands now?", default=False):
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
    disk = getattr(args, "disk", "disk0")
    container = getattr(args, "container", "disk0s2")
    windows_size = getattr(args, "windows_size", 128)
    esp_size = getattr(args, "esp_size", 512)
    macos_size = getattr(args, "macos_size", None)
    print("Partition plan (dry run; review before running):")
    print()
    print("1. Identify the target disk:")
    print("   diskutil list")
    print()
    print("2. Resize the macOS APFS container:")
    if macos_size is None:
        print(f"   diskutil apfs resizeContainer {container} <size>")
    else:
        print(f"   diskutil apfs resizeContainer {container} {macos_size // (1024**3)}g")
    print()
    print("3. Create an EFI System Partition:")
    print(f"   diskutil addPartition {disk} 1 'EFI System Partition' FAT32 WINM_ESP {esp_size}m")
    print()
    print("4. Create a Windows partition:")
    print(f"   diskutil addPartition {disk} 2 'Microsoft Basic Data' ExFAT WINM_WINDOWS {windows_size}g")
    print()
    print("5. Format WINM_WINDOWS as NTFS from Windows or WinPE before applying install.wim.")
    print("   macOS can create the partition, but NTFS formatting is not reliable on macOS.")
    print()
    print("Replace disk identifiers and sizes with values from 'diskutil list'.")
    print("Never run these commands without a full backup.")
    return 0



def build_partition_commands(
    disk: str, container: str, macos_size_bytes: int, esp_size_mib: int, windows_size_gib: int
) -> list[list[str]]:
    macos_size = f"{macos_size_bytes // (1024**3)}g"
    return [
        ["diskutil", "apfs", "resizeContainer", container, macos_size],
        ["diskutil", "addPartition", disk, "1", "EFI System Partition", "FAT32", "WINM_ESP", f"{esp_size_mib}m"],
        ["diskutil", "addPartition", disk, "2", "Microsoft Basic Data", "ExFAT", "WINM_WINDOWS", f"{windows_size_gib}g"],
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

