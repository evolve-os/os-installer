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
from .diskops import DiskOpCreateDisk
from .diskops import DiskOpCreateRoot
from .diskops import DiskOpCreateSwap
from .diskops import DiskOpCreateESP
from .diskops import DiskOpResizeOS
from .diskops import DiskOpUseSwap

MB = 1000 * 1000
GB = 1000 * MB
MIN_REQUIRED_SIZE = 10 * GB
SWAP_USE_THRESHOLD = 15 * GB
ESP_FREE_REQUIRED = 60 * MB
ESP_MIN_SIZE = 512


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

    supports_extended_partition = False

    def __init__(self, dp, drive):
        self.drive = drive
        self.dp = dp
        self.get_suitable_esp()
        self.reset_operations()

        if not self.drive.disk:
            return
        # Set up some common knowledge
        if drive.disk.supportsFeature(parted.DISK_TYPE_EXTENDED):
            self.supports_extended_partition = True

    def primary_exceeded(self):
        """ Determine if the count for primaries has been exceeded """
        if not self.drive.disk:
            return False
        maxp = self.drive.disk.maxPrimaryPartitionCount
        prim = self.drive.disk.getPrimaryPartitions()

        if len(prim) >= maxp:
            return True
        return False

    def logical_exceeded(self):
        """ Determine if the count for logicals has been exceeded """
        if not self.supports_extended_partition:
            return False
        maxl = self.drive.disk.maxLogicalPartitionCount
        logic = self.drive.getLogicalPartitions()

        if len(logic) >= maxl:
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

    def get_boot_loader_options(self):
        """ Normal options, i.e only wipe-disk is special """
        if not self.is_uefi():
            # MBR you can go anywhere you want.
            paths = [
                (self.dsc(x), x.path) for x in self.dp.drives
                if x.path != self.drive.path
            ]
            paths.append((self.dsc(self.drive), self.drive.path))
            paths.reverse()
            return paths
        esps = self.dp.collect_esp()
        if len(esps) == 0:
            # Create a new ESP
            return [("Create new ESP on {}".format(self.drive.path), "c")]
        cand = self.get_suitable_esp()
        # Have an ESP and it's not good enough for use.
        if not cand:
            self.set_errors(
                "ESP is too small: {} free space remaining".format(
                    cand.freespace_string))
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

    def __init__(self, dp, drive):
        DiskStrategy.__init__(self, dp, drive)
        self.drive = drive

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
                if x.path != self.drive.path
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
        size_eat = 0
        if info.bootloader_install:
            if info.bootloader_sz == 'c':
                size_eat += find_best_esp_size(self.drive.size)
                op = DiskOpCreateESP(self.drive.device, None, size_eat)
                self.push_operation(op)

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
        if self.is_uefi():
            t = "gpt"
        else:
            t = "msdos"
        self.push_operation(DiskOpCreateDisk(self.drive.device, t))
        # Let empty-disk handle the rest =)
        EmptyDiskStrategy.update_operations(self, dm, info)


class UseFreeSpaceStrategy(DiskStrategy):
    """ Use free space on the device """
    drive = None

    potential_spots = None
    candidate = None

    priority = 30

    def __init__(self, dp, drive):
        DiskStrategy.__init__(self, dp, drive)
        self.drive = drive
        self.potential_spots = []

    def get_display_string(self):
        sz = "Use the remaining free space on this disk and install a fresh" \
             " copy of Solus\nThis will <b>not affect</b> other systems."
        return sz

    def get_name(self):
        return "use-free-space: {}".format(self.drive.path)

    def is_possible(self):
        # No disk, should be empty-disk strategy
        if not self.drive.disk:
            return False
        # No partitions at all, empty-disk
        if len(self.drive.disk.partitions) == 0:
            return False
        extended = self.drive.disk.getExtendedPartition()
        if self.primary_exceeded() and not extended:
            # Cannot create a partition now
            return False
        # Build up a selection of free space partitions to use
        for part in self.drive.disk.getFreeSpacePartitions():
            size = part.getLength() * self.drive.device.sectorSize
            if size >= MIN_REQUIRED_SIZE:
                self.potential_spots.append(part)
        self.potential_spots.sort(key=parted.Partition.getLength, reverse=True)
        # Got at least one space big enough to use
        if len(self.potential_spots) > 0:
            # Pick the biggest guy
            self.candidate = self.potential_spots[0]
            return True
        return False


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

        size_eat = 0
        if info.bootloader_install:
            if info.bootloader_sz == 'c':
                size_eat += find_best_esp_size(self.drive.size)
                op = DiskOpCreateESP(self.drive.device, None, size_eat)
                self.push_operation(op)
        tnew -= size_eat

        # Find swap
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
                op = DiskOpCreateSwap(self.drive.device, None, new_swap_size)
                self.push_operation(op)

        # Create root
        op = DiskOpCreateRoot(self.drive.device, None, tnew)
        self.push_operation(op)

    def is_possible(self):
        # Require table
        if not self.drive.disk:
            return False

        for os_part in self.drive.operating_systems:
            if os_part not in self.drive.partitions:
                print("Warning: missing os_part: {}".format(os_part))
                continue
            partition = self.drive.partitions[os_part]
            if partition.size < MIN_REQUIRED_SIZE:
                continue
            if partition.freespace < MIN_REQUIRED_SIZE:
                continue
            if partition.partition.type == parted.PARTITION_NORMAL:
                if self.primary_exceeded():
                    print("Skipping OS due to excess")
                    continue
            else:
                if self.supports_extended_partition:
                    if self.logical_exceeded():
                        print("Skipping OS due to excess log")

            # Can continue
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
                self.candidate_part.size - self.candidate_part.usedspace)
            self.set_their_size(self.candidate_part.size - MIN_REQUIRED_SIZE)
            return True
        return False


class UserPartitionStrategy(DiskStrategy):
    """ Just for consistency and ease in integration, let the user do the
        partitioning """
    drive = None

    priority = 10

    def __init__(self, dp, drive):
        DiskStrategy.__init__(self, dp, drive)
        self.drive = drive

    def get_display_string(self):
        sz = "Create, resize and manually configure disk partitions yourself" \
             ". This method\nmay lead to <b>data loss.</b>"
        return sz

    def get_name(self):
        return "custom-partition: {}".format(self.drive.path)

    def is_possible(self):
        return self.drive.size >= MIN_REQUIRED_SIZE


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
                UseFreeSpaceStrategy,
                DualBootStrategy,
            ])
        for pot in strats:
            i = pot(self.prober, drive)
            if not i.is_possible():
                continue
            # Immediately update initial state
            ret.append(i)
        ret.sort(key=DiskStrategy.get_priority, reverse=True)
        return ret
