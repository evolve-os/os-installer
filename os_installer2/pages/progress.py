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

from .basepage import BasePage
from gi.repository import Gtk, GLib, Pango
import threading
import time
from collections import OrderedDict
from os_installer2 import SOURCE_FILESYSTEM, INNER_FILESYSTEM
from os_installer2.diskops import DiskOpCreateDisk, DiskOpResizeOS
from os_installer2.diskops import DiskOpCreatePartition
from os_installer2.diskops import DiskOpCreateESP
from os_installer2.diskops import DiskOpCreateLogicalVolume
from os_installer2.diskops import DiskOpCreateVolumeGroup
from os_installer2.diskops import DiskOpFormatRootLate
from os_installer2.diskops import DiskOpFormatSwapLate
from os_installer2.postinstall import PostInstallVfs
from os_installer2.postinstall import PostInstallRemoveLiveConfig
from os_installer2.postinstall import PostInstallSyncFilesystems
from os_installer2.postinstall import PostInstallMachineID
from os_installer2.postinstall import PostInstallKeyboard
from os_installer2.postinstall import PostInstallLocale
from os_installer2.postinstall import PostInstallTimezone
from os_installer2.postinstall import PostInstallUsers
from os_installer2.postinstall import PostInstallHostname
from os_installer2.postinstall import PostInstallDiskOptimize
from os_installer2.postinstall import PostInstallFstab
from os_installer2.postinstall import PostInstallUsysconf
from os_installer2.postinstall import PostInstallBootloader
import os
import stat
import parted
import sys
import shutil

# Update 5 times a second, vs every byte copied..
UPDATE_FREQUENCY = 1000 / 5


class InstallerProgressPage(BasePage):
    """ Actual installation :o """

    info = None
    progressbar = None
    label = None
    had_start = False
    installing = False
    mount_tracker = None
    temp_dirs = None

    # Our disk manager
    dm = None

    # Current string for the idle monitor to display in Gtk thread
    display_string = None

    # How much we need to copy
    filesystem_source_size = 0
    filesystem_copied_size = 0
    filesystem_copying = False
    past_simulation = False

    # Enabled post-install steps
    post_install_enabled = None

    # Are we in the post stage ?
    in_postinstall = False
    post_install_current = 0

    # Initialised post installs
    post_installs = None
    # Long-ass steps should pulse...
    should_pulse = False

    error_msgs = None

    def set_error_message(self, error_msg):
        """ Set the error message, i.e. something Super Bad happened """
        if not error_msg:
            error_msg = "[undefined error]"
        self.error_msgs.append(error_msg)

    def __init__(self):
        BasePage.__init__(self)

        self.error_msgs = []
        box = Gtk.Box.new(Gtk.Orientation.VERTICAL, 0)
        box.set_border_width(20)
        self.pack_end(box, False, False, 0)

        self.label = Gtk.Label("Initializing installer")
        self.label.set_max_width_chars(250)
        self.label.set_ellipsize(Pango.EllipsizeMode.END)
        self.label.set_halign(Gtk.Align.START)
        box.pack_start(self.label, True, True, 2)

        self.progressbar = Gtk.ProgressBar()
        box.pack_start(self.progressbar, False, False, 2)

        self.mount_tracker = OrderedDict()
        self.temp_dirs = []

        self.post_install_enabled = [
            PostInstallSyncFilesystems,
            PostInstallVfs,
            PostInstallRemoveLiveConfig,
            PostInstallMachineID,
            PostInstallKeyboard,
            PostInstallLocale,
            PostInstallTimezone,
            PostInstallUsers,
            PostInstallHostname,
            PostInstallDiskOptimize,
            PostInstallFstab,
            PostInstallUsysconf,
            PostInstallBootloader
        ]
        # Active postinstalls..
        self.post_installs = []

    def get_title(self):
        return "Installing Solus"

    def get_name(self):
        return "install"

    def get_icon_name(self, plasma=False):
        return "system-software-install"

    def get_sidebar_title(self):
        return "Install Solus"

    def begin_install(self):
        """ Begin the real work of doing the installation """
        # We don't yet do anything...
        self.label.set_markup("Warming up")

        self.installing = True
        # Hook up the idle monitor
        GLib.timeout_add(UPDATE_FREQUENCY, self.idle_monitor)
        t = threading.Thread(target=self.install_thread)
        t.start()

    def get_display_string(self):
        """ Ensure duped access for display string (threading..) """
        return str(self.display_string)

    def set_display_string(self, sz):
        """ Set the current display string """
        self.display_string = sz
        if not self.filesystem_copying:
            print(sz)

    def idle_monitor(self):
        """ Called periodicially so we can update our view """
        self.label.set_markup(self.get_display_string())
        if self.filesystem_copying:
            cp = float(self.filesystem_copied_size)
            tot = float(self.filesystem_source_size)
            if cp < tot and cp > 0:
                fraction = cp / tot
                self.progressbar.set_fraction(fraction)
            else:
                self.progressbar.pulse()
        elif self.in_postinstall:
            cur = float(self.post_install_current)
            tot = float(len(self.post_installs))
            if cur < tot and cur > 0 and not self.should_pulse:
                fraction = cur / tot
                self.progressbar.set_fraction(fraction)
            else:
                self.progressbar.pulse()
        else:
            self.progressbar.pulse()

        if not self.installing:
            print("Finished idle_monitor")
            GLib.idle_add(self.finish_installer)
        return self.installing

    def emit_errors(self):
        msg = "Issues were encountered during installaton"
        if not self.past_simulation:
            msg = "No changes have been made to your disk as simulation " \
                  "hasn't completed. The following errors were encountered: "
        else:
            msg = "Installation has failed, and changes were made to disk\n" \
                  "The installer will now exit."

        msg += "\n\n{}\n".format("\n".join(
            [str(x) for x in self.error_msgs]))
        d = Gtk.MessageDialog(parent=self.info.owner,
                              flags=Gtk.DialogFlags.MODAL,
                              type=Gtk.MessageType.ERROR,
                              buttons=Gtk.ButtonsType.OK,
                              message_format=msg)

        d.run()
        d.destroy()
        sys.exit(0)

    def finish_installer(self):
        """ Wrap things out and decide on the final call. """
        if len(self.error_msgs) > 0:
            self.emit_errors()
        else:
            print("Successful install!")
            self.info.owner.skip_page()
        return False

    def prepare(self, info):
        self.info = info
        self.dm = info.owner.get_disk_manager()
        self.info.owner.set_can_next(False)
        self.info.owner.set_can_previous(False)
        self.info.owner.set_can_quit(False)

        if not self.had_start:
            self.had_start = True
            self.begin_install()

    def _mkdtemp(self, suffix='installer'):
        """ Create and track the temporary directory """
        d = self.dm.create_temp_dir()
        if not d:
            return None
        self.temp_dirs.append(d)
        return d

    def get_mount_point_for(self, node):
        """ Get the mount point of a given node """
        if node in self.mount_tracker:
            return self.mount_tracker[node]
        return None

    def mount_esp(self, esp):
        """ Mount the ESP into the root """
        self.set_display_string("Mounting EFI System Partition")
        root = self.get_installer_target_filesystem()
        fpath = os.path.join(root, "boot")
        if not os.path.exists(fpath):
            try:
                os.makedirs(fpath, mode=0o755)
            except:
                return False

        if not self.dm.do_mount(esp, fpath, "auto"):
            return False
        self.mount_tracker[esp] = fpath
        return True

    def get_esp_target(self):
        """ convenience wrapper for postinstall """
        esp = self.locate_esp()
        return self.mount_tracker[esp]

    def mount_source_filesystem(self):
        """ Mount the source and child """
        source = self._mkdtemp()
        inner_path = os.path.join(source, INNER_FILESYSTEM)
        if not source:
            self.set_error_message("Cannot mkdtemp")
            return False

        # Try to mount the squashfs
        if not self.dm.do_mount(SOURCE_FILESYSTEM, source, "auto", "loop"):
            self.set_error_message("Cannot mount source filesystem")
            return False
        self.mount_tracker[SOURCE_FILESYSTEM] = source

        # See if the kid exists or not
        if not os.path.exists(inner_path):
            self.set_error_message("Cannot find {}".format(inner_path))
            return False

        inner_child = self._mkdtemp()
        # Try to mount the kid to a new temp
        if not inner_child:
            self.set_error_message("Cannot mkdtemp")
            return False
        if not self.dm.do_mount(inner_path, inner_child, "auto", "loop"):
            self.set_error_message("Cannot mount inner child")
            return False
        self.mount_tracker[INNER_FILESYSTEM] = inner_child

        # Now grab the size of the source filesystem
        try:
            vfs = os.statvfs(inner_child)
            size = (vfs.f_blocks - vfs.f_bfree) * vfs.f_frsize
            self.filesystem_source_size = size
        except Exception as e:
            self.set_error_message("Cannot compute source size: {}".format(e))
            return False

        return True

    def unmount_all(self):
        """ umount everything we've mounted """
        ret = True

        self.set_display_string("Unmounting filesystems - might take a while")

        # Visit in reverse order
        keys = self.mount_tracker.keys()
        keys.reverse()
        for key in keys:
            if not self.dm.do_umount(self.mount_tracker[key]):
                self.set_error_message("Cannot umount {}".format(key))
                ret = False

        for tmp in self.temp_dirs:
            try:
                os.rmdir(tmp)
            except Exception as e:
                self.set_error_message("Cannot rmdir {}: {}".format(
                    tmp, e))
                ret = False
        return ret

    def do_copy_file(self, source, dest):
        """ Simply copy a file .. """
        input = None
        dst = None

        try:
            BUF_SIZE = 16 * 1024
            input = open(source, "rb")
            dst = open(dest, "wb")
            while (True):
                read = input.read(BUF_SIZE)
                if not read:
                    break
                self.filesystem_copied_size += len(read)
                dst.write(read)
            input.close()
            dst.close()
            return True
        except Exception as ex:
            self.set_error_message(ex)
            if input:
                input.close()
            if dst:
                dst.close()
        return False

    def get_installer_target_filesystem(self):
        """ Get the mount point for the root partition for post-install """
        root = self.info.strategy.get_root_partition()
        root_fs = self.get_mount_point_for(root)
        return root_fs

    def get_installer_source_filesystem(self):
        """ Get the mount point for the source filesystem for post-install """
        source_fs = self.get_mount_point_for(INNER_FILESYSTEM)
        return source_fs

    def copy_system(self):
        """ Attempt to copy the entire filesystem across """
        print("Need to copy {} bytes".format(self.filesystem_source_size))

        source_fs = self.get_mount_point_for(INNER_FILESYSTEM)
        if not source_fs:
            return False
        root = self.info.strategy.get_root_partition()
        root_fs = self.get_mount_point_for(root)
        if not root_fs:
            self.set_error_message("Missing rootfs")
            return False

        self.filesystem_copying = True

        # Ensure we don't follow links, i.e. we're never in a situation where
        # we're creating broken leading directories
        for root, dirs, files in os.walk(source_fs,
                                         topdown=False,
                                         followlinks=False):
            # Mend the root to allow source/target use
            dir_root = root
            if dir_root.startswith(source_fs):
                dir_root = dir_root[len(source_fs):]
                if len(dir_root) > 0 and dir_root[0] != '/':
                    dir_root = "/" + dir_root

            # Do we skip this guy? Don't traverse what we don't need
            dir_base = dir_root.split("/")[0]
            if dir_base in ["home", "lost+found", "boot"]:
                continue

            # Create the container directory first
            target_dir = os.path.join(root_fs, dir_root[1:])
            if not os.path.exists(target_dir):
                try:
                    # We set the permissions up properly later
                    os.makedirs(target_dir, 0o0755)
                except Exception as ex:
                    self.set_error_message("Cannot create dir: {}".format(ex))
                    return False

            # Walk the tree from the back to restore permissions properly
            for f in files:
                source_path = os.path.join(source_fs, dir_root[1:], f)
                target_path = os.path.join(root_fs, dir_root[1:], f)

                # Not really necessary but meh
                self.set_display_string("Copying {}".format(
                    os.path.join(dir_root, f)))

                try:
                    st = os.lstat(source_path)
                    mode = stat.S_IMODE(st.st_mode)
                    is_link = False
                    is_copied = False

                    if stat.S_ISLNK(st.st_mode):
                        linkto = os.readlink(source_path)
                        os.symlink(linkto, target_path)
                        is_link = True
                    elif stat.S_ISCHR(st.st_mode):
                        os.mknod(target_path, stat.S_IFCHR | mode, st.st_rdev)
                    elif stat.S_ISBLK(st.st_mode):
                        os.mknod(target_path, stat.S_IFBLK | mode, st.st_rdev)
                    elif stat.S_ISFIFO(st.st_mode):
                        os.mknod(target_path, stat.S_IFIFO | mode)
                    elif stat.S_ISSOCK(st.st_mode):
                        os.mknod(target_path, stat.S_IFSOCK | mode)
                    elif stat.S_ISREG(st.st_mode):
                        is_copied = True
                        if not self.do_copy_file(source_path, target_path):
                            return False

                    # Chown it.
                    os.lchown(target_path, st.st_uid, st.st_gid)
                    if not is_link:
                        # Copy permissiions/utime
                        os.chmod(target_path, mode)
                        os.utime(target_path, (st.st_atime, st.st_mtime))
                    # copy_file handles size
                    if not is_copied:
                        self.filesystem_copied_size += st.st_size

                except Exception as ex:
                    self.set_error_message("Failed to copy {}".format(
                        source_path))
                    return False

            # Chown/utime the dirs as we come out, meaning we set perms/time
            # on everything but / itself
            for d in dirs:
                try:
                    target_path = os.path.join(root_fs, dir_root[1:], d)
                    source_path = os.path.join(source_fs, dir_root[1:], d)
                    self.set_display_string("Creating: {}".format(
                        os.path.join(dir_root, d)))
                    st = os.lstat(source_path)
                    mode = stat.S_IMODE(st.st_mode)
                    if not stat.S_ISDIR(st.st_mode):
                        linkto = os.readlink(source_path)
                        os.symlink(linkto, target_path)
                        os.lchown(target_path, st.st_uid, st.st_gid)
                        continue

                    os.chown(target_path, st.st_uid, st.st_gid)
                    os.chmod(target_path, mode)
                    os.utime(target_path, (st.st_atime, st.st_mtime))
                    # Update progress
                    self.filesystem_copied_size += st.st_size
                except Exception as ex:
                    self.set_error_message("Permissions issue: {} {}".format(
                        ex, d))
                    return False

        self.set_display_string("Finalizing file copy")
        return True

    def wait_disk(self, op):
        """ Wait for the disk to become available """
        if isinstance(op, DiskOpCreateLogicalVolume):
            p = op.part
        elif isinstance(op, DiskOpCreateVolumeGroup):
            p = op.path
        else:
            p = op.part.path

        self.set_display_string("Verifying existence of {}".format(p))
        count = 0
        while (count < 5):
            if os.path.exists(p):
                return True
            self.set_display_string("Waiting for {}".format(p))
            time.sleep(0.5)
            count += 1
        if not os.path.exists(p):
            self.set_error_message("Couldn't locate {}".format(p))
            return False
        return True

    def round_up_next_block(self, num, size):
        """ Given an end sector and blocksize, round to the block """
        mod = num % size
        return num + size - mod

    def apply_disk_strategy(self, simulate):
        """ Attempt to apply the given disk strategy """
        strategy = self.info.strategy
        ops = strategy.get_operations()

        table_ops = [x for x in ops if isinstance(x, DiskOpCreateDisk)]
        resizes = [x for x in ops if isinstance(x, DiskOpResizeOS)]
        if len(table_ops) > 1:
            self.set_error_message("Wiping disk more than once, error")
            return False
        if len(resizes) > 1:
            self.set_error_message("Multiple resizes not supported")
            return False

        # Madman time: Go apply the operations. *Gulp*
        disk = strategy.disk
        if disk and simulate:
            disk = disk.duplicate()

        part_offset = 0
        part_step = parted.sizeToSectors(1, 'MiB', strategy.device.sectorSize)
        if disk:
            # Start at the very beginning of the disk, we don't
            # support free-space installation
            part_offset = self.round_up_next_block(disk.getFirstPartition().geometry.end, part_step)
        for op in ops:
            self.set_display_string(op.describe())
            op.set_part_offset(part_offset)
            if not op.apply(disk, simulate):
                er = op.get_errors()
                if not er:
                    er = "Failed to apply operation: {}".format(op.describe())
                self.set_error_message(er)
                return False
            # If it created a disk, go use it.
            if isinstance(op, DiskOpCreateDisk):
                disk = op.disk
                if not strategy.disk:
                    strategy.disk = disk
                # Now set the part offset
                part_offset = self.round_up_next_block(disk.getFirstPartition().geometry.end, part_step)
            elif isinstance(op, DiskOpResizeOS):
                part_offset = self.round_up_next_block(op.new_part_off, part_step)
            elif isinstance(op, DiskOpCreatePartition):
                # Push forward the offset
                part_offset = self.round_up_next_block(op.part_end,part_step)

        if simulate:
            return True

        try:
            disk.commit()
        except Exception as e:
            self.set_error_message("Failed to update disk: {}".format(e))
            return False

        try:
            os.system("sync")
        except:
            pass

        # Post-process, format all the things
        post_types = [
            DiskOpCreatePartition,
            DiskOpCreateLogicalVolume,
            DiskOpCreateVolumeGroup,
            DiskOpFormatRootLate,
            DiskOpFormatSwapLate,
        ]

        for op in ops:
            is_type = False
            for t in post_types:
                if isinstance(op, t):
                    is_type = True
                    break
            if not is_type:
                continue
            # Wait for device to show up!
            if isinstance(op, DiskOpCreatePartition):
                if not self.wait_disk(op):
                    return False

            p = op.describe()
            self.set_display_string("Applying operation: {}".format(p))
            if not op.apply_format(disk):
                e = op.get_errors()
                self.set_error_message("Failed to apply format: {}".format(e))
                print(op.describe())
                return False

        return True

    def mount_target_filesystem(self):
        """ Mount our target filesystem(s) """
        strategy = self.info.strategy

        root = strategy.get_root_partition()
        if not root or root.strip() == "":
            self.set_error_message("Fatal: Missing root partition")
            return False
        target = self._mkdtemp()
        if not target:
            self.set_error_message("Cannot create temporary root directory")
            return False
        if not self.dm.do_mount(root, target, "auto", "rw"):
            self.set_error_message("Cannot mount root partition")
            return False
        self.mount_tracker[root] = target

        print("DEBUG: / ({}) mounted at {}".format(root, target))
        return True

    def maybe_nuke_live(self):
        fpath = os.path.join(self.get_installer_target_filesystem(),
                             "home/live")
        if not os.path.exists(fpath):
            return True
        try:
            shutil.rmtree(fpath)
        except Exception:
            return False
        return True

    def maybe_mount_home(self):
        strategy = self.info.strategy
        home = strategy.get_home_dir()
        if not home:
            return True
        target = os.path.join(self.get_installer_target_filesystem(),
                              "home")
        if not self.dm.do_mount(home, target, "auto", "rw"):
            self.set_error_message("Cannot mount home partition")
            return False
        self.mount_tracker[home] = target

        print("DEBUG: /home ({}) mounted at {}".format(home, target))
        return True

    def maybe_mount_boot(self):
        strategy = self.info.strategy
        boot = strategy.get_boot_partition()
        if not boot:
            return True
        target = os.path.join(self.get_installer_target_filesystem(),
                              "boot")
        if not os.path.exists(target):
            try:
                os.makedirs(target, mode=0o755)
            except:
                return False
        if not self.dm.do_mount(boot, target, "auto", "rw"):
            self.set_error_message("Cannot mount boot partition")
            return False
        self.mount_tracker[boot] = target

        print("DEBUG: /boot ({}) mounted at {}".format(boot, target))
        return True

    def install_thread(self):
        """ Handle the real work of installing =) """
        self.set_display_string("Analyzing installation configuration")

        # immediately gain privs
        self.info.owner.get_perms_manager().up_permissions()

        # Simulate!
        self.set_display_string("Simulating disk operations")
        print("SIMULATING")
        if not self.apply_disk_strategy(True):
            self.installing = False
            self.set_error_message("Failed to simulate disk strategy")
            return False

        self.past_simulation = True
        print("NO LONGER SIMULATING")
        # Now do it for real.
        if not self.apply_disk_strategy(False):
            self.installing = False
            self.set_error_message("Failed to apply disk strategy")
            return False

        # Now mount up as it were.
        if not self.mount_source_filesystem():
            self.unmount_all()
            self.set_error_message("Failed to mount!")
            self.installing = False
            return False

        # Mount the / filesystem
        if not self.mount_target_filesystem():
            self.unmount_all()
            self.set_error_message("Failed to mount target!")
            self.installing = False
            return False

        # If we have a /boot, mount it here
        if not self.maybe_mount_boot():
            self.set_error_message("Failed to mount /boot")
            self.unmount_all()
            self.installing = False
            return False

        # Mount the ESP
        if self.info.strategy.is_uefi():
            esp = self.locate_esp()
            if not esp:
                self.unmount_all()
                self.set_error_message("Failed to locate ESP!")
                self.installing = False
                return False
            if not self.mount_esp(esp):
                self.unmount_all()
                self.set_error_message("Failed to mount ESP!")
                self.installing = False
                return False

        # Copy source -> target
        if not self.copy_system():
            self.filesystem_copying = False
            self.unmount_all()
            self.installing = False
            return False
        self.filesystem_copying = False

        if not self.maybe_nuke_live():
            self.set_error_message("Failed to clean /home")
            self.unmount_all()
            self.installing = False
            return False

        if not self.maybe_mount_home():
            self.set_error_message("Failed to mount /home")
            self.unmount_all()
            self.installing = False
            return False

        time.sleep(1)
        self.set_display_string("Initializing post-installs")
        for ptype in self.post_install_enabled:
            r = ptype(self.info, self)
            self.set_display_string("Initialised {}".format(
                r.get_display_string()))
            self.post_installs.append(r)

        # Now run the post-installs
        self.in_postinstall = True
        for step in self.post_installs:
            self.should_pulse = step.is_long_step()
            disp = step.get_display_string()
            self.set_display_string(disp)
            try:
                b = step.apply()
                if not b:
                    self.set_error_message(step.get_errors())
            except Exception as e:
                b = False
                self.set_display_string(e)
            if not b:
                self.set_error_message(step.get_errors())
                # Failed :(
                self.in_postinstall = False
                self.unmount_all()
                self.installing = False
                return False
            self.post_install_current += 1

        # Actually made it. :o
        self.in_postinstall = False

        # Ensure the idle monitor stops
        if not self.unmount_all():
            self.set_error_message("Failed to unmount cleanly!")

        self.installing = False

    def locate_esp(self):
        """ Locate selected ESP """
        if not self.info.bootloader_install:
            return None
        if not self.info.strategy.is_uefi():
            return None

        for op in self.info.strategy.get_operations():
            if isinstance(op, DiskOpCreateESP):
                return op.part.path
        return self.info.bootloader_sz
