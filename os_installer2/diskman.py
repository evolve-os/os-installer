#!/bin/true
# -*- coding: utf-8 -*-
#
#  This file is part of os-installer
#
#  Copyright 2013-2016 Ikey Doherty <ikey@solus-project.com>
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 2 of the License, or
#  (at your option) any later version.
#

from . import format_size_local
from . import MIN_REQUIRED_SIZE
from gi.repository import GObject
import re
import os
import subprocess
import tempfile
import time
import parted
import struct


class DriveProber:
    """ Handle the mundane work of probing and querying all of the drives """

    # Our disk manager
    dm = None

    drives = None
    mtab = None

    def __init__(self, dm):
        self.dm = dm

    def get_drive(self, nom):
        """ Return a named drive """
        for item in self.drives:
            if item.path == nom:
                return item

    def probe_lvm2(self):
        cmds = ["/sbin/pvscan", "/sbin/vgscan", "/sbin/lvscan"]
        for cmd in cmds:
            try:
                subprocess.check_call(cmd)
            except Exception as e:
                print("Failed to execute {}: {}".format(cmd, e))
                return False
        return True

    def collect_esp(self):
        """ util """
        ret = set()
        for i in self.drives:
            for x in i.list_esp:
                ret.add(x)
        r = list(ret)
        r.sort(key=SystemPartition.getLength, reverse=True)
        return r

    def probe(self):
        """ Probe all the drives for juicy information """
        self.drives = list()

        # Cache the current mount points, gonna need it.
        self.mtab = self.dm.get_mount_points()
        self.dm.scan_parts()
        self.probe_lvm2()

        for item in self.dm.devices:
            disk = None
            device = None
            try:
                device = parted.getDevice(item)
                if device.readOnly:
                    print("DEBUG: Skipping read-only device")
                    continue
                size = device.getLength() * device.sectorSize
                if size < MIN_REQUIRED_SIZE:
                    print("DEBUG: Skipping tiny drive: {}".format(
                          device.path))
                    continue
            except Exception as e:
                print("Cannot probe device: {} {}".format(item, e))
                continue
            try:
                disk = parted.Disk(device)
            except Exception as e:
                print("Cannot probe disk: {} {}".format(item, e))

            # Get a system drive
            drive = self.dm.parse_system_disk(device, disk, self.mtab)
            if drive:
                self.drives.append(drive)

    def is_broken_windows_uefi(self):
        """ Determine if we booted with UEFI on a MBR Windows system """
        if not self.dm.is_efi_booted():
            return False
        gpt_disks = [x for x in self.drives if x.get_disk_type() == "gpt"]
        have_windows = False
        efi_sps = []
        for drive in self.drives:
            win = [x for x in drive.operating_systems.values()
                   if x.otype == "windows"]
            if len(win) != 0:
                have_windows = True
            efi_sps.extend(drive.list_esp)

        if not have_windows:
            return False
        # No GPT? Instafail
        if len(gpt_disks) == 0:
            return True
        # No ESP? Also fail
        if len(efi_sps) == 0:
            return True
        # All seems good here.
        return False


class SystemPartition(GObject.Object):
    """ Wrapper around partition information """

    __gtype_name__ = "OsSystemPartition"

    # Our parted.Partition reference
    partition = None

    # Our actual path, i.e. /dev/sda3
    path = None
    resizable = False

    # How much free space remains, in bytes and with string rep
    freespace = None
    freespace_string = None

    # How much total space this
    totalspace = None
    totalspace_string = None
    sizeString = None

    # How much used space in bytes, with string rep
    usedspace = None
    usedspace_string = None

    # Actual size of this partition
    size = None

    # Absolute minimum size as reported by the filesystem
    min_size = None

    def getLength(self):
        """ Purely for sort compat """
        return self.size

    def build_ntfs_space(self):
        """ Figure out ntfs minimum size """
        cmd = "LANG=C ntfsresize -im --no-action {}".format(self.path)

        try:
            o = subprocess.check_output(cmd, shell=True)
        except Exception as ex:
            print("Cannot resize ntfs: {}".format(ex))
            return

        for l in o.split("\n"):
            if ":" not in l:
                continue
            if "MB" not in l:
                continue
            min_size = long(l.split(":")[-1].strip())
            self.min_size = min_size * 1000 * 1000
            self.resizable = True
            break

    def build_ext_space(self):
        """ Figure out ext* min size """
        cmd = "LANG=C resize2fs -P {}".format(self.path)

        try:
            o = subprocess.check_output(cmd, shell=True)
        except Exception as ex:
            print("Cannot resize ext4: {}".format(ex))
            return

        for l in o.split("\n"):
            if ":" not in l:
                continue
            if "minimum size" not in l:
                continue
            min_size = long(l.split(":")[-1].strip())
            self.min_size = min_size * 4096 / 1024

            # Handle 1/2k blocks
            if self.min_size < self.usedspace:
                self.min_size = self.usedspace
            self.resizable = True
            break

    def __init__(self, partition, mount_point, dm):
        GObject.GObject.__init__(self)
        self.partition = partition
        self.path = partition.path

        sectorSize = self.partition.disk.device.sectorSize
        self.size = self.partition.getLength() * sectorSize
        self.sizeString = format_size_local(self.size, True)

        # Get the free space available here
        try:
            vfs = os.statvfs(mount_point)
            self.freespace = vfs.f_bavail * vfs.f_frsize
            self.totalspace = vfs.f_blocks * vfs.f_frsize
            self.usedspace = (vfs.f_blocks - vfs.f_bavail) * vfs.f_frsize

            self.freespace_string = format_size_local(self.freespace)
            self.totalspace_string = format_size_local(self.totalspace)
            self.usedspace_string = format_size_local(self.usedspace)
        except Exception as e:
            print("Failed to stat {}: {}".format(mount_point, e))

        # Now work out if we're resizable.
        fs = partition.fileSystem
        if not fs:
            return
        if fs.type == "ntfs":
            try:
                self.build_ntfs_space()
            except Exception as e:
                print("Undefined error in ntfs: {}".format(e))
        elif fs.type in ["ext2", "ext", "ext3", "ext4"]:
            try:
                self.build_ext_space()
            except Exception as e:
                print("Undefined error in ext*: {}".format(e))


class SystemDrive:
    """ Handy helper for monitoring disks """

    # The parted.Device
    device = None

    # The parted.Disk
    disk = None

    # Vendor of the device
    vendor = None

    # Model of the device
    model = None

    # Localised size representation with units
    sizeString = None

    # Actual size in bytes
    size = None

    # Mapping of partition -> OsType
    operating_systems = None

    # Make accessing the path easier..
    path = None

    # List of EFI System Partitions
    list_esp = None

    # Encapsulated partitions
    partitions = None

    def __init__(self, device, disk, vendor, model, sizeString, ops):
        self.device = device
        self.disk = disk
        self.vendor = vendor
        self.model = model
        self.sizeString = sizeString
        self.operating_systems = ops
        self.path = device.path
        self.partitions = dict()

        self.size = self.device.getLength() * self.device.sectorSize

    def get_swap_partitions(self):
        """ Get all swap partititons """
        parts = []
        if not self.disk:
            return parts
        for part in self.disk.partitions:
            if not part.fileSystem:
                continue
            if part.fileSystem.type in ["linux-swap(v1)", "linux-swap(v0)"]:
                parts.append(part)
        parts.sort(key=parted.Partition.getLength, reverse=True)
        return parts

    def get_display_string(self):
        """ Format usable in UIs """
        return "{} {} ({})".format(self.device.model,
                                   self.sizeString,
                                   self.device.path)

    def get_disk_type(self):
        """ Return the disk type, if any """
        if self.disk:
            return self.disk.type
        return None


class OsType:
    """ OS detection code ensuring we don't lose information """

    # Valid: windows, windows-boot, linux, none
    otype = None

    # String name for this detected Thing.
    name = None

    # The device_path this OS was found on
    device_path = None

    # Icon name for use in user interfaces
    icon_name = None

    def __init__(self, otype, name, device_path):
        self.otype = otype
        self.name = name
        self.device_path = device_path


class DiskManager:
    """ Manage all disk operations """

    re_whole_disk = None
    re_mmcblk = None
    re_nvme = None
    re_raid = None
    devices = None

    win_prefixes = None
    win_bootloaders = None

    is_uefi = False
    uefi_fw_size = 64
    host_size = 64
    efi_types = None

    os_icons = None

    def __init__(self):
        # Gratefully borrowed from gparted, Proc_Partitions_Info.cc
        self.re_whole_disk = re.compile(
            "^[\t ]+[0-9]+[\t ]+[0-9]+[\t ]+[0-9]+[\t ]+([^0-9]+)$")
        self.re_mmcblk = re.compile(
            "^[\t ]+[0-9]+[\t ]+[0-9]+[\t ]+[0-9]+[\t ]+(mmcblk[0-9]+)$")
        self.re_nvme = re.compile(
            "^[\t ]+[0-9]+[\t ]+[0-9]+[\t ]+[0-9]+[\t ]+(nvme[0-9]+n[0-9]+)$")
        self.re_raid = re.compile(
            "^[\t ]+[0-9]+[\t ]+[0-9]+[\t ]+[0-9]+[\t ]+(md[0-9]+)$")

        # Rough versioning matches for Windows
        self.win_prefixes = {
            "10.": "Windows 10",
            "6.3": "Windows 8.1",
            "6.2": "Windows 8",
            "6.1": "Windows 7",
            "6.0": "Windows Vista",
            "5.2": "Windows XP",
            "5.1": "Windows XP",
            "5.0": "Windows 2000",
            "4.90": "Windows Me",
            "4.1": "Windows 98",
            "4.0.1381": "Windows NT",
            "4.0.950": "Windows 95",
        }

        # Rough match for BCD
        self.win_bootloaders = {
            "V.i.s.t.a": "Windows Vista bootloader",
            "W.i.n.d.o.w.s. .7": "Windows 7 bootloader",
            "W.i.n.d.o.w.s. .R.e.c.o.v.e.r.y. .E.n.v.i.r.o.n.m.e.n.t":
                "Windows recovery",
            "W.i.n.d.o.w.s. .S.e.r.v.e.r. .2.0.0.8":
                "Windows Server 2008 bootloader"
        }

        # Set up UEFI knowledge
        if os.path.exists("/sys/firmware/efi"):
            self.is_uefi = True
            pl_f = "/sys/firmware/efi/fw_platform_size"
            if os.path.exists(pl_f):
                pl_s = self._read_line_complete(pl_f)
                if pl_s == "64":
                    self.uefi_fw_size = 64
                elif pl_s == "32":
                    self.uefi_fw_size = 32
                else:
                    print("System reported odd FW size: {}".format(pl_s))
        else:
            self.is_uefi = False
        # Valid EFI types
        self.efi_types = ["fat", "fat32", "fat16", "vfat", "fat12"]

        # host size setup (64/32)
        if struct.calcsize("P") * 8 < 64:
            self.host_size = 32
        else:
            self.host_size = 64

        # For populating OsType's
        self.os_icons = [
            "antergos", "archlinux", "crunchbang", "debian", "deepin",
            "edubuntu", "elementary", "fedora", "frugalware", "gentoo",
            "kubuntu", "linux-mint", "mageia", "mandriva", "manjaro",
            "solus", "opensuse", "slackware", "steamos", "ubuntu-gnome",
            "ubuntu-mate", "ubuntu"
        ]

    def is_efi_system_partition(self, partition):
        """ Is the given partition an EFI System Partition (ESP) ? """
        disk = partition.disk
        if not disk:
            return False
        # Must be on a gpt disk
        if disk.type != "gpt":
            return False
        fs = partition.fileSystem
        if not fs:
            return False
        # needs to be a valid EFI type
        if fs.type not in self.efi_types:
            return False
        # Also needs to be bootable
        if not partition.getFlag(parted.PARTITION_BOOT):
            return False
        return True

    def scan_parts(self):
        self.devices = []
        try:
            part_file = open("/proc/partitions")
        except Exception as ex:
            print("Failed to scan parts: {}".format(ex))
            return

        groups = [self.re_whole_disk,
                  self.re_mmcblk,
                  self.re_nvme,
                  self.re_raid]

        for line in part_file.readlines():
            # readlines doesn't consume
            line = line.replace("\r", "").replace("\n", "")

            for x in groups:
                m = x.match(line)
                if not m:
                    continue
                self.push_device(m.group(1))
                break

        part_file.close()

    def push_device(self, device):
        """ Push a newly discovered device into the list """
        fpath = "/dev/{}".format(str(device))
        if not os.path.exists(fpath):
            print("Debug: Non-existent node: {}".format(fpath))
            return
        fpath = os.path.realpath(fpath)
        if device not in self.devices:
            self.devices.append(fpath)

    @staticmethod
    def is_device_ssd(path):
        """ Determine if the device is an SSD """
        nodename = os.path.basename(path)
        fpath = "/sys/block/{}/queue/rotational".format(nodename)
        if not os.path.exists(fpath):
            return False

        # Don't try using SSD trim with eMMC
        if nodename.startswith("mmcblk"):
            return False

        try:
            with open(fpath, "r") as inp_file:
                items = inp_file.readlines()
                if len(items) == 1:
                    line = items[0].replace("\n", "").replace("\r", "")
                    if line == "0":
                        return True
        except Exception:
            pass
        return False

    def is_install_supported(self, path):
        """ Currently we only support rootfs installs on certain types... """
        nodename = os.path.basename(path)
        if nodename.startswith("md"):
            return False
        return True

    def get_mount_points(self):
        """ Return a mapping of device to mountpoint """
        ret = dict()

        with open("/proc/self/mounts", "r") as mpoints:
            for line in mpoints.readlines():
                line = line.replace("\n", "").replace("\r", "").strip()

                if line == "":
                    continue
                splits = line.split()
                if len(splits) < 4:
                    continue
                dev = splits[0]
                mpoint = splits[1]

                # Only interested in block devices
                if dev[0] != '/':
                    continue

                ret[os.path.abspath(os.path.realpath(dev))] = mpoint
        return ret

    def do_mount(self, device, mpoint, fsystem, options=None):
        """ Try to mount the device at mount_point """
        mount_cmd = "mount -t {} {} \"{}\"".format(fsystem, device, mpoint)

        if options:
            mount_cmd += " -o {}".format(options)

        try:
            subprocess.check_call(mount_cmd, shell=True)
        except Exception as e:
            print("Failed to mount {} to {}: {}".format(device, mpoint, e))
            return False
        return True

    def do_umount(self, thing):
        """ umount the given mountpoint/device """
        umount_cmd = "umount \"{}\"".format(thing)
        try_count = 0

        while (try_count < 3):
            try_count += 1
            try:
                subprocess.check_call(umount_cmd, shell=True)
                return True
            except Exception:
                # wait 500ms, try again
                time.sleep(0.5)
                continue

        umount_cmd = "umount -l \"{}\"".format(thing)
        try:
            subprocess.check_call(umount_cmd)
            return True
        except Exception as e:
            print("Failed to unmount {}: {}".format(thing, e))
            return False

        # Finally umounted with lazy.
        return True

    def get_windows_version(self, path):
        """ Attempt to gain the Windows version """
        fpath = os.path.join(path, "Windows/servicing/Version")
        if not os.path.exists(fpath):
            # Still Windows of some variety
            fpath = os.path.join(path, "Windows/System32")
            if os.path.exists(fpath):
                return "Windows (Unknown)"
            # Definitely not Windows.
            return None

        try:
            r = os.listdir(fpath)
        except Exception:
            return None

        vers = None
        if len(r) > 0:
            r = sorted(r, reverse=True)
        elif len(r) == 0:
            return "Corrupt Windows Installation"
        vers = r[0]

        for item in self.win_prefixes:
            if vers.startswith(item):
                return self.win_prefixes[item]

        return "Windows (Unknown)"

    def get_windows_bootloader(self, path):
        """ Determine the bootloader version """
        fpath = os.path.join(path, "Boot/BCD")
        if not os.path.exists(fpath):
            return None

        for key in self.win_bootloaders:
            cmd = "grep -qs \"{}\" \"{}\"".format(key, fpath)
            try:
                subprocess.check_call(cmd)
                return self.win_bootloaders[key]
            except Exception:
                continue

        return "Windows bootloader"

    def extract_os_release_key(self, path, find_key):
        """ Grab a key from the given os-release file """
        with open(path, "r") as inp_file:
            for line in inp_file.readlines():
                line = line.replace("\r", "").replace("\n", "").strip()
                if line == "":
                    continue

                if "=" not in line:
                    continue
                splits = line.split("=")
                key = splits[0].lower()
                val = "=".join(splits[1:]).strip()

                if len(val) == 0:
                    continue
                if val[0] == "\"":
                    val = val[1:]
                if val[-1] == "\"":
                    val = val[0:-1]

                if key != find_key.lower():
                    continue
                return val
        return None

    def get_linux_version(self, path):
        """ Attempt to get the Linux version string """
        # os-release files, with stateless support
        os_paths = [
            "etc/os-release",
            "usr/lib/os-release"
        ]
        # lsb-release files, with stateless support
        lsb_paths = [
            "etc/lsb-release",
            "usr/lib/lsb-release",
            "usr/share/defaults/etc/lsb-release"
        ]

        key_checks = [
            ("PRETTY_NAME", "NAME", os_paths),
            ("DISTRIB_DESCRIPTION", "DISTRIB_ID", lsb_paths),
        ]

        # Iterate os-release files and then fallback to lsb-release files,
        # respecting stateless heirarchy
        for key_main, key_fallback, paths in key_checks:
            for item in paths:
                fpath = os.path.join(path, item)
                if not os.path.exists(fpath):
                    continue

                pname = self.extract_os_release_key(fpath, key_main)
                if not pname:
                    pname = self.extract_os_release_key(fpath, key_fallback)
                if not pname:
                    continue
                return pname

        return None

    def get_os_icon(self, os):
        """ Return the display icon for a given OS """
        if os.otype == "windows" or os.otype == "windows-boot":
            return "distributor-logo-windows"
        elif os.otype != "linux":
            return "system-software-install"

        # Explicit copy and then mangle
        mangled = str(os.name).strip().lower()
        mangled = mangled.replace(" ", "-")

        for x in self.os_icons:
            if mangled.startswith(x):
                return "distributor-logo-{}".format(x)
        return "system-software-install"

    def create_temp_dir(self, suffix='installer'):
        """ Create a named temp dir. If it fails, return none """
        try:
            mdir = tempfile.mkdtemp(suffix=suffix)
            return mdir
        except Exception as e:
            print("Error constructing temp directory: {}".format(e))
            return None

    def detect_operating_system_and_space(self, device, mpoints):
        """ Determine the operating system and space for a given device """
        mounted = False
        mount_point = None

        path = device.path

        fs = device.fileSystem
        # unmountables
        if fs and fs.type in [None, "linux-swap(v1)", "linux-swap(v0)"]:
            return (None, None)

        # Mount it if not already mounted
        if path not in mpoints:
            mount_point = self.create_temp_dir()
            if not mount_point:
                return (None, None)

            if not self.do_mount(path, mount_point, "auto", "ro"):
                try:
                    os.rmdir(mount_point)
                except Exception as e:
                    print("Failed to remove stagnant directory: {}".format(e))
                return (None, None)
            mounted = True
        else:
            # Reuse existing mountpoint
            mount_point = mpoints[path]

        possibles = [
            ("windows", self.get_windows_version),
            ("windows-boot", self.get_windows_bootloader),
            ("linux", self.get_linux_version),
        ]

        ret = None

        for os_type, vfunc in possibles:
            dname = vfunc(mount_point)
            if dname:
                ret = OsType(os_type, dname, device)
                ret.icon_name = self.get_os_icon(ret)
                break

        part = SystemPartition(device, mount_point, self)
        # Unmount again
        if mounted:
            if self.do_umount(mount_point):
                try:
                    os.rmdir(mount_point)
                except Exception as e:
                    print("Failed to remove stagnant directory: {}".format(e))
            else:
                print("Warning: {} {} still mount".format(path, mount_point))
        return (part, ret)

    def _read_line_complete(self, path):
        with open(path, "r") as inp:
            l = inp.readlines()[0].strip().replace("\r", "").replace("\n", "")
            return l
        return None

    def get_disk_model(self, device):
        """ Get the model of the device """
        node = os.path.basename(device)
        fpath = "/sys/block/{}/device/model".format(node)

        if not os.path.exists(fpath):
            return None
        return self._read_line_complete(fpath)

    def get_disk_vendor(self, device):
        """ Get the vendor for the device """
        node = os.path.basename(device)
        fpath = "/sys/block/{}/device/vendor".format(node)

        if not os.path.exists(fpath):
            return None
        return self._read_line_complete(fpath)

    def get_disk_size_bytes(self, device):
        """ Return byte length of disk (parted.Device) """
        return device.getLength() * device.sectorSize

    def get_disk_size_string(self, device):
        """ Return formatted size of disk (parted.Device) """
        return format_size_local(self.get_disk_size_bytes(device))

    def is_efi_booted(self):
        """ Determine if we booted using UEFI """
        return self.is_uefi

    def get_platform_size(self):
        """ 64-bit or 32-bit firmware """
        return self.uefi_fw_size

    def parse_system_disk(self, device, disk, mpoints):
        """ Parse a given parted.Disk into a SystemDevice """
        operating_systems = dict()
        list_esp = list()
        partitions = dict()

        blacklist = []

        for mpoint in mpoints:
            whence = mpoints[mpoint]
            if whence == "/" or whence.startswith("/run/initramfs"):
                blacklist.append(mpoint)

        # i.e. /dev/sda, full write mount
        if device.path in blacklist:
            print("DEBUG: Skipping boot disk")
            return None

        # Could be a disk without a label
        if disk:
            # i.e. /dev/sda1, partition mount
            for partition in disk.partitions:
                if partition.path in blacklist:
                    print("DEBUG: Skipping boot disk")
                    return None

                if not partition.fileSystem:
                    continue

                (part, os) = self.detect_operating_system_and_space(partition,
                                                                    mpoints)
                if self.is_efi_system_partition(partition):
                    list_esp.append(part)
                partitions[partition.path] = part
                if not os:
                    continue
                operating_systems[partition.path] = os

        sz = self.get_disk_size_string(device)

        vendor = self.get_disk_vendor(device.path)
        model = self.get_disk_model(device.path)
        r = SystemDrive(device, disk, vendor, model, sz, operating_systems)
        # Cache ESP
        r.list_esp = list_esp
        r.list_esp.sort(key=SystemPartition.getLength, reverse=True)
        r.partitions = partitions
        return r
