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

import parted
from .diskman import SystemPartition
from .diskops import DummyPart
from .diskops import DiskOpCreateDisk
from .diskops import DiskOpCreateRoot
from .diskops import DiskOpCreateSwap
from .diskops import DiskOpCreateESP
from .diskops import DiskOpFormatRoot
from .diskops import DiskOpFormatRootLate
from .diskops import DiskOpResizeOS
from .diskops import DiskOpUseSwap
from .diskops import DiskOpFormatSwap
from .diskops import DiskOpFormatSwapLate
from .diskops import DiskOpFormatHome
from .diskops import DiskOpUseHome
from .diskops import DiskOpCreateBoot
from .diskops import DiskOpCreatePhysicalVolume
from .diskops import DiskOpCreateLUKSPhysicalVolume
from .diskops import DiskOpCreateLUKSContainer
from .diskops import DiskOpCreateVolumeGroup
from .diskops import DiskOpCreateLogicalVolume
from . import MIN_REQUIRED_SIZE, MB, GB


SWAP_USE_THRESHOLD = 15 * GB
ESP_FREE_REQUIRED = 60 * MB
ESP_MIN_SIZE = 512

BOOT_MIN_SIZE = 300 * MB


def find_best_swap_size(longsize):
    gbs = longsize / GB
    if gbs > 50:
        return 4 * GB
    elif gbs > 40:
        return 2 * GB
    else:
        return 1 * GB


def find_best_esp_size(longsize):
    gbs = longsize / GB
    if gbs < 20:
        return 250 * MB
    return 512 * MB


class DiskStrategy:
    """ Base DiskStrategy does nothing """

    priority = 0
    drive = None
    dp = None
    errors = None
    operations = None
    device = None
    disk = None

    supports_extended_partition = False

    def get_home_dir(self):
        return None

    def get_boot_partition(self):
        """ On LVM2 setups with BIOS we create a /boot partition """
        return None

    def get_root_partition(self):
        print("FATAL: Unimplemented strategy!!")
        return None

    def __init__(self, dp, drive):
        self.drive = drive
        self.dp = dp
        self.get_suitable_esp()
        self.reset_operations()
        self.device = self.drive.device

        if not self.drive.disk:
            return
        self.disk = self.drive.disk
        # Set up some common knowledge
        if drive.disk.supportsFeature(parted.DISK_TYPE_EXTENDED):
            self.supports_extended_partition = True

    def primary_exceeded(self, addPrimaries=0):
        """ Determine if the count for primaries has been exceeded """
        if not self.drive.disk:
            return False
        maxp = self.drive.disk.maxPrimaryPartitionCount
        prim = self.drive.disk.getPrimaryPartitions()

        if len(prim) + addPrimaries >= maxp:
            return True
        return False

    def logical_exceeded(self, addLogicals=0):
        """ Determine if the count for logicals has been exceeded """
        if not self.supports_extended_partition:
            return False
        maxl = self.drive.disk.getMaxLogicalPartitions()
        logic = self.drive.disk.getLogicalPartitions()

        if len(logic) + addLogicals >= maxl:
            return True
        return False

    def set_errors(self, errors):
        self.errors = errors

    def get_errors(self):
        return self.errors

    def get_display_string(self):
        return "Fatal Error"

    def get_name(self):
        return "-fatal-"

    def is_possible(self):
        return False

    def get_priority(self):
        return self.priority

    def explain(self, dm, info):
        """ Step by step explanation of what we're doing to do. """
        ret = []
        for step in self.operations:
            ret.append(step.describe())
        return ret

    def is_uefi(self):
        """ proxy """
        return self.dp.dm.is_efi_booted()

    def get_suitable_esp(self):
        """ Attempt to find the suitable ESP.... """
        l = self.dp.collect_esp()
        if not l:
            return None
        e = l[0]
        if e.freespace < ESP_FREE_REQUIRED:
            return None
        return e

    def dsc(self, thing):
        device = None
        if isinstance(thing, SystemPartition):
            device = thing.partition.disk.device
        else:
            device = thing.device
        return "{} {} ({})".format(
            device.model, thing.sizeString, thing.path)

    def would_create_esp(self):
        """ Determine if we're required to create an ESP """
        if not self.is_uefi():
            return False

        if len(self.dp.collect_esp()) == 0:
            return True

    def get_boot_loader_options(self):
        """ Normal options, i.e only wipe-disk is special """
        if not self.is_uefi():
            # MBR you can go anywhere you want.
            paths = [
                (self.dsc(x), x.path) for x in self.dp.drives
                if x.path != self.drive.path and x.disk.type == "msdos"
            ]
            if self.drive.disk and self.drive.disk.type == "msdos":
                paths.append((self.dsc(self.drive), self.drive.path))
            paths.reverse()
            return paths
        esps = self.dp.collect_esp()
        if len(esps) == 0 and not isinstance(self, UserPartitionStrategy):
            # Create a new ESP
            return [("Create new ESP on {}".format(self.drive.path), "c")]
        cand = self.get_suitable_esp()
        # Have an ESP and it's not good enough for use.
        if not cand:
            if esps:
                self.set_errors(
                    "ESP is too small: {} free space remaining".format(
                        esps[0].freespace_string))
            else:
                self.set_errors("No usable ESP found on this system")
            return []
        return [(self.dsc(cand), cand.path)]

    def reset_operations(self):
        """ Reset the current operations """
        self.operations = []

    def push_operation(self, op):
        self.operations.append(op)

    def get_operations(self):
        """ Get the operations associated with this strategy """
        return self.operations

    def update_operations(self, dm, info):
        """ Implementations should push_operation here """
        pass


class EmptyDiskStrategy(DiskStrategy):
    """ There is an empty disk, use this if it is big enough """
    drive = None

    priority = 50

    use_lvm2 = False
    use_encryption = False
    enc_password = None

    def __init__(self, dp, drive):
        DiskStrategy.__init__(self, dp, drive)
        self.drive = drive

    def get_boot_partition(self):
        for op in self.get_operations():
            if not isinstance(op, DiskOpCreateBoot):
                continue
            return op.part.path

    def requires_separate_boot(self):
        """ Determine if we need a separate boot partition too """
        if self.is_uefi():
            # Never need /boot with UEFI
            return False
        if self.use_lvm2:
            return True
        return False

    def get_display_string(self):
        sz = "Automatically partition this empty disk and install a fresh " \
             "copy of Solus."
        return sz

    def get_name(self):
        return "empty-disk: {}".format(self.drive.path)

    def is_possible(self):
        if self.drive.size < MIN_REQUIRED_SIZE:
            return False
        # No MBR/header
        if not self.drive.disk:
            return True
        if len(self.drive.disk.partitions) == 0:
            return True
        # Probably wipe-disk
        return False

    def get_boot_loader_options(self):
        if not self.is_uefi():
            # MBR you can go anywhere you want.
            paths = [
                (self.dsc(x), x.path) for x in self.dp.drives
                if x.path != self.drive.path and x.disk is not None and
                x.disk.type == "msdos"
            ]
            paths.append((self.dsc(self.drive), self.drive.path))
            paths.reverse()
            return paths
        esps = self.dp.collect_esp()
        if len(esps) == 0:
            return [("Create new ESP on {}".format(self.drive.path), "c")]
        cand = self.get_suitable_esp()
        # Are we overwriting this ESP?
        if self.drive.disk and esps[0].partition.disk == self.drive.disk:
            return [("Create new ESP on {}".format(self.drive.path), "c")]
        if not cand:
            self.set_errors(
                "ESP is too small: {} free space remaining".format(
                    cand.freespace_string))
            return []
        return [(self.dsc(cand), cand.path)]

    def update_operations(self, dm, info):
        """ Handle all the magicks """
        if self.is_uefi():
            t = "gpt"
        else:
            t = "msdos"
        # Need a part table
        self.push_operation(DiskOpCreateDisk(self.drive.device, t))

        size_eat = 0
        if info.bootloader_install:
            # *Always* consume an ESP
            if info.bootloader_sz == 'c':
                size_eat += find_best_esp_size(self.drive.size)
                op = DiskOpCreateESP(self.drive.device, None, size_eat)
                self.push_operation(op)

        # Create LVM2 base specifics
        if self.use_lvm2:
            # First things first, let's create /boot. Always need this even
            # if we don't explicitly install GRUB itself
            if not self.is_uefi():
                size_eat += BOOT_MIN_SIZE
                op = DiskOpCreateBoot(self.drive.device, None, size_eat)
                self.push_operation(op)

            # NAUGHTY! Figure out a unique LVM2 ID
            vg_name = "SolusSystem"
            if not self.use_encryption:
                pv_op = DiskOpCreatePhysicalVolume(
                    self.drive.device, None, self.drive.size - size_eat)
                self.push_operation(pv_op)
            else:
                # First move, create a LUKS Container
                luks_op = DiskOpCreateLUKSContainer(
                    self.drive.device, None, self.drive.size - size_eat,
                    self.enc_password)
                self.push_operation(luks_op)

                # Now create a physical volume on the LUKS Container
                pv_op = DiskOpCreateLUKSPhysicalVolume(
                    self.drive.device, luks_op)
                self.push_operation(pv_op)

            # From here on out everything is identical.
            vg_op = DiskOpCreateVolumeGroup(self.drive.device, pv_op, vg_name)
            self.push_operation(vg_op)

            # Can we create swap?
            tnew = self.drive.size - size_eat
            if tnew >= SWAP_USE_THRESHOLD:
                new_swap_size = find_best_swap_size(self.drive.size)
                tnew -= new_swap_size
                size = "{}B".format(new_swap_size)
                # Create swap volume
                op = DiskOpCreateLogicalVolume(
                    self.drive.device, vg_name, "Swap", size)
                self.push_operation(op)
                # Format the swap on the LVM2 LV
                self.push_operation(DiskOpFormatSwapLate(
                    self.drive.device, DummyPart(op.path)))
                # Mark it used and get the path in place
                self.push_operation(DiskOpUseSwap(
                    self.drive.device, DummyPart(op.path)))

            # Create a root partition on the whole thang from remaining space
            lv_op = DiskOpCreateLogicalVolume(
                self.drive.device, vg_name, "Root", "100%FREE")
            self.push_operation(lv_op)
            # Format the root partition
            self.push_operation(DiskOpFormatRootLate(
                self.drive.device, DummyPart(lv_op.path)))

            return

        # Attempt to create a local swap
        tnew = self.drive.size - size_eat
        if tnew >= SWAP_USE_THRESHOLD:
            new_swap_size = find_best_swap_size(self.drive.size)
            tnew -= new_swap_size
            op = DiskOpCreateSwap(self.drive.device, None, new_swap_size)
            self.push_operation(op)
            size_eat += new_swap_size

        root_size = self.drive.size - size_eat
        op = DiskOpCreateRoot(self.drive.device, None, root_size)
        self.push_operation(op)

    def get_root_partition(self):
        """ Get our root partition """
        for op in self.get_operations():
            # For LVM2 just look for the "Root" LV
            if self.use_lvm2:
                if isinstance(op, DiskOpCreateLogicalVolume):
                    if op.lv_name == "Root":
                        return op.path
            else:
                # Look for where we explicitly create /
                if isinstance(op, DiskOpCreateRoot):
                    return op.part.path
        return None


class WipeDiskStrategy(EmptyDiskStrategy):
    """ We simply wipe and take over a complete disk """
    drive = None

    priority = 20

    def __init__(self, dp, drive):
        EmptyDiskStrategy.__init__(self, dp, drive)
        self.drive = drive

    def get_display_string(self):
        sz = "Erase all content on this disk and install a fresh copy of " \
             "Solus\nThis will <b>destroy all existing data on the disk</b>."
        return sz

    def get_name(self):
        return "wipe-disk: {}".format(self.drive.path)

    def is_possible(self):
        if self.drive.size < MIN_REQUIRED_SIZE:
            return False
        # No table, use empty-disk strategy
        if not self.drive.disk:
            return False
        # This is an empty-disk strategy
        if len(self.drive.disk.partitions) == 0:
            return False
        return True

    def update_operations(self, dm, info):
        # Let empty-disk handle the rest =)
        EmptyDiskStrategy.update_operations(self, dm, info)


class DualBootStrategy(DiskStrategy):
    """ Dual-boot alongside the biggest install by resizing it """
    drive = None
    potential_spots = None
    candidate_part = None

    # Selected OS name
    candidate_os = None

    # Selected OS
    sel_os = None
    priority = 40

    our_size = 0
    their_size = 0

    def __init__(self, dp, drive):
        DiskStrategy.__init__(self, dp, drive)
        self.drive = drive
        self.potential_spots = []

    def get_display_string(self):
        os = self.candidate_os
        sz = "Install a fresh copy of Solus alongside your existing " \
             "Operating System.\nYou can choose how much space Solus should " \
             "use in the next screen.\nThis will resize <b>{}</b>.".format(os)
        return sz

    def get_name(self):
        return "dual-boot: {}".format(self.candidate_os)

    def set_our_size(self, sz):
        self.our_size = sz

    def set_their_size(self, sz):
        self.their_size = sz

    def update_operations(self, dm, info):
        """ First up, resize them """
        op = DiskOpResizeOS(
            self.drive.device, self.candidate_part,
            self.candidate_os, self.their_size, self.our_size)
        self.push_operation(op)

        tnew = self.our_size

        # Root only
        part_count = 1

        size_eat = 0
        if info.bootloader_install:
            if info.bootloader_sz == 'c':
                size_eat += find_best_esp_size(self.drive.size)
                op = DiskOpCreateESP(self.drive.device, None, size_eat)
                self.push_operation(op)
                part_count += 1
        tnew -= size_eat

        # Determine if swap is possible given our partition count
        can_swap = True
        if self.candidate_part.partition.type == parted.PARTITION_LOGICAL:
            if self.logical_exceeded(part_count):
                can_swap = False
        else:
            if self.primary_exceeded(part_count):
                can_swap = False

        # Find swap
        if can_swap:
            swap = self.drive.get_swap_partitions()
            swap_part = None
            if swap:
                swap_part = swap[0]
            if swap_part:
                op = DiskOpUseSwap(self.drive.device, swap_part)
                self.push_operation(op)
            else:
                if tnew >= SWAP_USE_THRESHOLD:
                    new_swap_size = find_best_swap_size(self.our_size)
                    tnew -= new_swap_size
                    op = DiskOpCreateSwap(self.drive.device,
                                          None, new_swap_size)
                    self.push_operation(op)

        # Create root
        op = DiskOpCreateRoot(self.drive.device, None, tnew)
        self.push_operation(op)

    def is_possible(self):
        # Require table
        if not self.drive.disk:
            return False

        if self.is_uefi():
            if self.drive.disk.type != "gpt":
                return False
        else:
            if self.drive.disk.type != "msdos":
                return False

        self.potential_spots = []
        # The absolute minimum number of partitions we need (swap = bonus.)
        min_partitions = 1
        if self.would_create_esp():
            min_partitions += 1

        for os_part in self.drive.operating_systems:
            if os_part not in self.drive.partitions:
                print("Warning: missing os_part: {}".format(os_part))
                continue
            partition = self.drive.partitions[os_part]
            if not partition.resizable:
                continue
            # Skip guys that are too small
            if partition.size - partition.min_size < MIN_REQUIRED_SIZE:
                continue
            if partition.freespace < MIN_REQUIRED_SIZE:
                continue
            if partition.partition.type == parted.PARTITION_NORMAL:
                if self.primary_exceeded(min_partitions):
                    # "Skipping OS due to excess"
                    continue
            else:
                if self.supports_extended_partition:
                    if self.logical_exceeded(min_partitions):
                        # "Skipping OS due to excess log"
                        continue
            # Can continue
            fs = partition.partition.fileSystem
            if not fs:
                continue
            if fs.type == "ntfs" or fs.type.startswith("ext"):
                self.potential_spots.append(partition)

        self.potential_spots.sort(key=SystemPartition.getLength,
                                  reverse=True)

        if len(self.potential_spots) > 0:
            self.candidate_part = self.potential_spots[0]
            self.sel_os = \
                self.drive.operating_systems[self.candidate_part.path]
            self.candidate_os = self.sel_os.name
            # Default to using the whole thing =P
            self.set_our_size(
                self.candidate_part.size - self.candidate_part.min_size)
            self.set_their_size(self.candidate_part.size - MIN_REQUIRED_SIZE)
            return True
        return False

    def get_root_partition(self):
        """ Get our root partition """
        for op in self.get_operations():
            if isinstance(op, DiskOpCreateRoot):
                return op.part.path
        return None


class ReplaceOSStrategy(DiskStrategy):
    """ Replace the biggest OS with us """

    priority = 30

    potential_spots = None
    candidate_part = None

    # Selected OS name
    candidate_os = None

    # Selected OS
    sel_os = None

    def __init__(self, dp, drive):
        DiskStrategy.__init__(self, dp, drive)

    def get_display_string(self):
        os = self.candidate_os
        sz = "Replace your existing <b>{}</b> installation with Solus.\n" \
             "All data on this partition will be destroyed before installing" \
             " a fresh copy of Solus.".format(os)
        return sz

    def get_name(self):
        return "replace-os: {}".format(self.candidate_os)

    def is_possible(self):
        # Require table
        if not self.drive.disk:
            return False

        if self.is_uefi():
            if self.drive.disk.type != "gpt":
                return False
        else:
            if self.drive.disk.type != "msdos":
                return False

        self.potential_spots = []

        for os_part in self.drive.operating_systems:
            os = self.drive.operating_systems[os_part]
            # Don't try to nuke Windows. People seem attached to it.
            if os.otype in ["windows", "windows-boot"]:
                continue
            if os_part not in self.drive.partitions:
                print("Warning: missing os_part: {}".format(os_part))
                continue
            partition = self.drive.partitions[os_part]
            if partition.size < MIN_REQUIRED_SIZE:
                continue
            self.potential_spots.append(partition)

        self.potential_spots.sort(key=SystemPartition.getLength,
                                  reverse=True)

        if len(self.potential_spots) > 0:
            self.candidate_part = self.potential_spots[0]
            self.sel_os = \
                self.drive.operating_systems[self.candidate_part.path]
            self.candidate_os = self.sel_os.name
            return True
        return False

    def update_operations(self, dm, info):
        """ First up, resize them """
        if info.bootloader_install:
            if info.bootloader_sz == 'c':
                size = find_best_esp_size(self.drive.size)
                op = DiskOpCreateESP(self.drive.device, None, size)
                self.push_operation(op)

        swap = self.drive.get_swap_partitions()
        # Bonus, free swap
        if swap:
            swap_part = swap[0]
            op = DiskOpUseSwap(self.drive.device, swap_part)
            self.push_operation(op)

        # Create root
        op = DiskOpFormatRoot(self.drive.device,
                              self.candidate_part.partition)
        self.push_operation(op)

    def get_root_partition(self):
        """ Get our root partition """
        for op in self.get_operations():
            if isinstance(op, DiskOpFormatRoot):
                return op.part.path
        return None


class UserPartitionStrategy(DiskStrategy):
    """ Just for consistency and ease in integration, let the user do the
        partitioning """
    drive = None

    priority = 10

    root_part = None
    home_part = None
    home_format = False
    home_fstype = None
    swap_part = None
    swap_format = False

    def get_home_dir(self):
        for op in self.get_operations():
            if not isinstance(op, DiskOpUseHome):
                continue
            return op.path

    def get_root_partition(self):
        """ Get our root partition """
        for op in self.get_operations():
            if isinstance(op, DiskOpFormatRoot):
                return op.part.path
        return None

    def set_root_partition(self, part, fstype):
        """ Set the root partition to use """
        self.root_part = part
        self.home_fstype = fstype

    def set_home_partition(self, part, fmt, fstype):
        """ Set the home partition to use and maybe format """
        self.home_part = part
        self.home_format = fmt
        self.home_fstype = fstype

    def set_swap_partition(self, part, fmt):
        """ Set the swap partition to use and maybe format """
        self.swap_part = part
        self.swap_format = fmt

    def __init__(self, dp, drive):
        DiskStrategy.__init__(self, dp, drive)
        self.drive = drive

    def get_display_string(self):
        sz = "Assign mount points to partitions you have previously created." \
             "\nThese must already exist prior to launching the installer. If"\
             "\nyou modify them, please restart the installer."
        return sz

    def get_name(self):
        return "custom-partition: {}".format(self.drive.path)

    def is_possible(self):
        return self.drive.size >= MIN_REQUIRED_SIZE

    def find_device(self, dp, path):
        for drive in dp.drives:
            for part in drive.partitions:
                if part == path:
                    return drive.device
            for part in drive.get_swap_partitions():
                if part == path:
                    return drive.device

    def find_format(self, dp, dev):
        path = dev.path
        for drive in dp.drives:
            for part in drive.partitions:
                print("{} vs {}".format(part, path))
                if part == path:
                    return drive.partitions[part].partition.fileSystem.type

    def update_operations(self, dm, info):
        if not self.root_part:
            return
        dev = self.find_device(info.prober, self.root_part)
        self.push_operation(DiskOpFormatRoot(dev, self.root_part))

        if self.swap_part:
            dev = self.find_device(info.prober, self.swap_part)
            if not self.swap_format:
                self.push_operation(DiskOpUseSwap(dev, self.swap_part))
            else:
                self.push_operation(DiskOpFormatSwap(dev, self.swap_part))
                self.push_operation(DiskOpUseSwap(dev, self.swap_part))
        if self.home_part:
            dev = self.find_device(info.prober, self.home_part)
            if not self.home_format:
                self.home_fstype = self.find_format(info.prober, self.home_part)
                self.push_operation(DiskOpUseHome(dev, self.home_part, self.home_fstype))
            else:
                self.push_operation(DiskOpFormatHome(dev, self.home_part, self.home_fstype))
                self.push_operation(DiskOpUseHome(dev, self.home_part, self.home_fstype))


class DiskStrategyManager:
    """ Strategy manager for installation solutions """

    prober = None
    broken_uefi = False

    def __init__(self, prober):
        self.prober = prober
        self.broken_uefi = prober.is_broken_windows_uefi()

    def get_strategies(self, drive):
        ret = []
        # Possible strategies
        strats = [
            WipeDiskStrategy,
            UserPartitionStrategy,
            EmptyDiskStrategy,
        ]
        # In short, you're in the wrong mode.
        if not self.broken_uefi:
            strats.extend([
                DualBootStrategy,
                ReplaceOSStrategy,
            ])
        for pot in strats:
            i = pot(self.prober, drive)
            if not i.is_possible():
                continue
            # Immediately update initial state
            ret.append(i)
        ret.sort(key=DiskStrategy.get_priority, reverse=True)
        return ret
