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

import subprocess
import os
from collections import OrderedDict
from .diskman import DiskManager
from .diskops import DiskOpCreateSwap, DiskOpUseSwap, DiskOpUseHome
from .diskops import DiskOpCreateBoot
from .diskops import DiskOpCreateLUKSContainer
from .strategy import EmptyDiskStrategy
import shutil


def get_part_uuid(path, part_uuid=False):
    """ Get the UUID of a given partition """
    col = "PARTUUID" if part_uuid else "UUID"
    cmd = "blkid -s {} -o value {}".format(col, path)
    try:
        o = subprocess.check_output(cmd, shell=True)
        o = o.split("\n")[0]
        o = o.replace("\r", "").replace("\n", "").strip()
        return o
    except Exception as e:
        print("UUID lookup failed: {}".format(e))
        return None


class PostInstallStep:
    """ Basic post-install API """

    # Tracking operations
    info = None

    # Installer reference for doing the hard lifting
    installer = None

    # Errors for this obj
    errors = None

    def __init__(self, info, installer):
        self.info = info
        self.installer = installer

    def apply(self):
        """ Apply this post-install step """
        print("NOT IMPLEMENTED!")
        return False

    def get_display_string(self):
        return "I AM NOT IMPLEMENTED!"

    def set_errors(self, err):
        """ Set the errors for this step """
        self.errors = err

    def get_errors(self):
        """ Get the errors, if any, for this step """
        return self.errors

    def run_in_chroot(self, command):
        """ Helper to enable quick boolean chroot usage """
        full_cmd = "LC_ALL=C chroot \"{}\" /bin/sh -c \"{}\"".format(
            self.installer.get_installer_target_filesystem(),
            command)
        try:
            subprocess.check_call(full_cmd, shell=True)
        except Exception as e:
            self.set_errors(e)
            return False
        return True

    def is_long_step(self):
        """ Override when this is a long operation and the progressbar should
            pulse, so the user doesn't believe the UI locked up """
        return False


class PostInstallVfs(PostInstallStep):
    """ Set up the virtual filesystems required for all other steps """

    vfs_points = None

    def __init__(self, info, installer):
        PostInstallStep.__init__(self, info, installer)
        self.vfs_points = OrderedDict([
            ("/dev", "{}/dev"),
            ("/dev/shm", "{}/dev/shm"),
            ("/dev/pts", "{}/dev/pts"),
            ("/sys", "{}/sys"),
            ("/proc", "{}/proc"),
        ])

    def get_display_string(self):
        return "Setting up virtual filesystems"

    def apply(self):
        target = self.installer.get_installer_target_filesystem()
        for source_point in self.vfs_points:
            target_point = self.vfs_points[source_point].format(target)
            cmd = "mount --bind {} \"{}\"".format(source_point, target_point)
            try:
                subprocess.check_call(cmd, shell=True)
                self.installer.mount_tracker[source_point] = target_point
            except Exception as e:
                self.set_errors("Failed to bind-mount vfs: {}".format(e))
                return False
        return True


class PostInstallRemoveLiveConfig(PostInstallStep):
    """ Remove the live user from the filesystem """

    """ Packages that are of no use to the user, i.e. us. """
    live_packages = None
    original_source = None
    modified_files = None

    def __init__(self, info, installer):
        PostInstallStep.__init__(self, info, installer)
        self.live_packages = [
            "os-installer",
        ]
        # Find the branding package to nuke
        if os.path.exists("/usr/bin/mate-panel"):
            self.live_packages.append("mate-desktop-branding-livecd")
        elif os.path.exists("/usr/bin/gnome-shell"):
            self.live_packages.append("gnome-desktop-branding-livecd")
        elif os.path.exists("/usr/bin/plasmashell"):
            self.live_packages.append("plasma-desktop-branding-livecd")
        else:
            self.live_packages.append("budgie-desktop-branding-livecd")

        self.original_source = "/usr/share/os-installer"
        self.modified_files = [
            "/etc/gdm/custom.conf"
        ]

    def get_display_string(self):
        return "Removing live configuration"

    def apply(self):
        # Forcibly remove the user (TODO: Make all this configurable... )
        if not self.run_in_chroot("userdel -fr live"):
            return False

        # Return live-specific packages
        cmd_remove = "eopkg remove {} --ignore-comar".format(
            " ".join(self.live_packages))
        if not self.run_in_chroot(cmd_remove):
            self.set_errors("Failed to remove live packages")
            return False

        # Replace the modified
        target_fs = self.installer.get_installer_target_filesystem()

        for replacement in self.modified_files:
            bname = os.path.basename(replacement)
            source_file = os.path.join(self.original_source, bname)
            target_file = os.path.join(target_fs, replacement[1:])

            if not os.path.exists(source_file):
                continue
            target_dir = os.path.dirname(target_file)
            if not os.path.exists(target_dir):
                try:
                    os.makedirs(target_dir, 0o0755)
                except Exception as e:
                    self.set_errors("Cannot mkdir: {}".format(e))
                    return False
            try:
                shutil.copy2(source_file, target_file)
            except Exception as e:
                self.set_errors("Cannot update file: {}".format(e))
                return False

        # Remove sudo
        if not self.run_in_chroot("rm /etc/sudoers.d/os-installer"):
            return False
        return True

    def is_long_step(self):
        """ Have to remove packages and users, compile schemas, etc """
        return True


class PostInstallSyncFilesystems(PostInstallStep):
    """ Just call sync, nothing fancy """

    def __init__(self, info, installer):
        PostInstallStep.__init__(self, info, installer)

    def get_display_string(self):
        return "Flushing buffers to disk.. please wait"

    def is_long_step(self):
        return True

    def apply(self):
        try:
            subprocess.check_call("sync", shell=True)
        except:
            pass
        return True


class PostInstallMachineID(PostInstallStep):
    """ Initialise the machine-id """

    def __init__(self, info, installer):
        PostInstallStep.__init__(self, info, installer)

    def get_display_string(self):
        return "Creating machine-id for new installation"

    def apply(self):
        fp = os.path.join(self.installer.get_installer_target_filesystem(),
                          "etc/machine-id")
        # Delete existing machine-id
        if os.path.exists(fp):
            try:
                os.remove(fp)
            except Exception as e:
                self.set_errors(e)
                return False

        # Now create a new machine-id
        if not self.run_in_chroot("systemd-machine-id-setup"):
            self.set_errors("Failed to construct machine-id")
            return False
        return True


# We use this guy to set the global layout..
KEYBOARD_CONFIG_TEMPLATE = """
# Read and parsed by systemd-localed. It's probably wise not to edit this file
# manually too freely.
Section "InputClass"
        Identifier "system-keyboard"
        MatchIsKeyboard "on"
        Option "XkbModel" "%(XKB_MODEL)s"
        Option "XkbLayout" "%(XKB_LAYOUT)s"
EndSection
"""


class PostInstallKeyboard(PostInstallStep):
    """ Set the keyboard layout on the target device """

    def __init__(self, info, installer):
        PostInstallStep.__init__(self, info, installer)

    def get_display_string(self):
        return "Storing keyboard configuration"

    def apply(self):
        xkb_model = "pc104"
        x11dir = os.path.join(self.installer.get_installer_target_filesystem(),
                              "etc/X11/xorg.conf.d")
        x11file = os.path.join(x11dir, "00-keyboard.conf")

        # create the x11 dir
        if not os.path.exists(x11dir):
            try:
                os.makedirs(x11dir, 0o0755)
            except Exception as ex:
                self.set_errors(ex)
                return False

        # set up the template
        tmpl = KEYBOARD_CONFIG_TEMPLATE % {
            'XKB_MODEL': xkb_model, 'XKB_LAYOUT': self.info.keyboard
        }

        # write the template to disk
        tmpl = tmpl.strip() + "\n"
        try:
            with open(x11file, "w") as xfile:
                os.chmod(x11file, 0o0644)
                xfile.write(tmpl)
        except Exception as ex:
            self.set_errors(ex)
            return False
        return True


class PostInstallLocale(PostInstallStep):
    """ Set the system locale """

    def __init__(self, info, installer):
        PostInstallStep.__init__(self, info, installer)

    def get_display_string(self):
        return "Storing system locale"

    def apply(self):
        lang = self.info.locale

        # Dump to locale.conf
        fpath = os.path.join(self.installer.get_installer_target_filesystem(),
                             "etc/locale.conf")
        try:
            with open(fpath, "w") as localef:
                os.chmod(fpath, 0o0644)
                if not lang.endswith(".utf8"):
                    lc = lang.split(".")[0]
                    lang = "{}.utf8".format(lc)
                localef.write("LANG={}\n".format(lang))
        except Exception as e:
            self.set_errors(e)
            return False
        return True


ADJTIME_LOCAL = """
0.0 0 0.0
0
LOCAL
"""


class PostInstallTimezone(PostInstallStep):
    """ Set up the timezone """

    def __init__(self, info, installer):
        PostInstallStep.__init__(self, info, installer)

    def get_display_string(self):
        return "Storing system timezone"

    def apply(self):
        """ Link /etc/localtime up to zoneinfo """
        loc = self.info.timezone
        self.run_in_chroot("rm -f /etc/localtime")
        cmd = "ln -sf \"/usr/share/zoneinfo/{}\" /etc/localtime".format(loc)
        if not self.run_in_chroot(cmd):
            self.set_errors("Failed to set timezone")
            return False

        if not self.info.windows_present:
            return True

        # Set adjtime to local for Windows users
        adjp = os.path.join(self.installer.get_installer_target_filesystem(),
                            "etc/adjtime")
        try:
            with open(adjp, "w") as adjtime:
                os.chmod(adjp, 0o0644)
                adjtime.write(ADJTIME_LOCAL.strip() + "\n")
        except Exception as e:
            print("Warning: Failed to update adjtime: {}".format(e))
        return True


class PostInstallUsers(PostInstallStep):
    """ Add users to the new installation """

    normal_groups = None
    admin_groups = None

    def __init__(self, info, installer):
        PostInstallStep.__init__(self, info, installer)

        self.normal_groups = [
            "audio",
            "video",
            "cdrom",
            "dialout",
            "fuse",
            "users",
        ]
        self.admin_groups = [
            "sudo",
            "lpadmin",
            "plugdev",
            "scanner",
        ]

    def get_display_string(self):
        return "Creating users"

    def apply(self):
        """ Add all of the system users """

        pwd_file = []

        # Add all the users.
        for user in self.info.users:
            groups = []
            groups.extend(self.normal_groups)
            if user.admin:
                groups.extend(self.admin_groups)

            cmd = "useradd -s {} -c '{}' -G {} -m {}".format(
                "/bin/bash",  # Default shell in Solus
                user.realname,
                ",".join(groups),
                user.username)

            try:
                self.run_in_chroot(cmd)
            except Exception as e:
                self.set_errors("Cannot configure user: {}".format(e))
                return False

            pwd_file.append("{}:{}".format(user.username, user.password))

        f = os.path.join(self.installer.get_installer_target_filesystem(),
                         "tmp/newusers.conf")

        # Pass off the passwords to chpasswd
        pwds_done = False
        fd = None
        try:
            fd = open(f, "w")
            fd.write("\n".join(pwd_file))
            fd.close()
            fd = None
            self.run_in_chroot("cat /tmp/newusers.conf | chpasswd")
            os.remove(f)
            pwds_done = True
        except Exception as e:
            self.set_errors("Unable to update passwords: {}".format(e))

        if fd:
            fd.close()

        if not pwds_done:
            try:
                os.remove(f)
            except:
                pass
            return False

        # Disable the root account
        if not self.run_in_chroot("passwd -d root"):
            self.set_errors("Failed to disable root account")
            return False
        return True


class PostInstallHostname(PostInstallStep):
    """ Set up the hostname """

    def __init__(self, info, installer):
        PostInstallStep.__init__(self, info, installer)

    def get_display_string(self):
        return "Setting the system hostname"

    def apply(self):
        hosts = [
            "127.0.0.1\tlocalhost",
            "127.0.0.1\t{}".format(self.info.hostname),
            "# The following lines are desirable for IPv6 capable hosts",
            "::1     localhost ip6-localhost ip6-loopback",
            "fe00::0 ip6-localnet",
            "ff00::0 ip6-mcastprefix",
            "ff02::1 ip6-allnodes",
            "ff02::2 ip6-allrouters",
            "ff02::3 ip6-allhosts"
        ]

        bpath = self.installer.get_installer_target_filesystem()
        hostname_file = os.path.join(bpath, "etc/hostname")
        hosts_file = os.path.join(bpath, "etc/hosts")
        try:
            with open(hostname_file, "w") as hout:
                os.chmod(hostname_file, 0o0644)
                hout.write("{}\n".format(self.info.hostname))
            with open(hosts_file, "w") as hpout:
                os.chmod(hosts_file, 0o0644)
                hpout.write("\n".join(hosts) + "\n")
        except Exception as e:
            self.set_errors("Failed to configure hosts: {}".format(e))
            return False
        return True


class PostInstallDiskOptimize(PostInstallStep):
    """ Optimize disk usage """

    def __init__(self, info, installer):
        PostInstallStep.__init__(self, info, installer)

    def get_display_string(self):
        return "Optimizing the disk configuration"

    def apply(self):
        dev_path = self.info.strategy.drive.path

        cmd = None
        if DiskManager.is_device_ssd(dev_path):
            cmd = "systemctl enable fstrim.timer"
        else:
            # TODO: Support readahead
            return True

        if not self.run_in_chroot(cmd):
            self.set_errors("Unable to apply disk optimizations")
            return False
        return True

class PostInstallUsysconf(PostInstallStep):
    """ Run usysconf for the target """

    def __init__(self, info, installer):
        PostInstallStep.__init__(self, info, installer)

    def get_display_string(self):
        return "Running usysconf"

    def apply(self):
        """ Perform a full usysconf run """
        try:
            self.run_in_chroot("usysconf run -f")
        except Exception as e:
            self.set_errors("Failed to run usysconf: {}".format(e))
            return False
        return True

    def is_long_step(self):
        """ Its.. just long. Seriously """
        return True

FSTAB_HEADER = """
# /etc/fstab: static file system information.
#
# <fs>      <mountpoint> <type> <opts>      <dump/pass>

# /dev/ROOT   /            ext3    noatime        0 1
# /dev/SWAP   none         swap    sw             0 0
# /dev/fd0    /mnt/floppy  auto    noauto         0 0
none        /proc        proc    nosuid,noexec  0 0
none        /dev/shm     tmpfs   defaults       0 0
"""


class PostInstallFstab(PostInstallStep):
    """ Write the fstab to disk """

    def __init__(self, info, installer):
        PostInstallStep.__init__(self, info, installer)

    def get_display_string(self):
        return "Writing filesystem mount points"

    def apply(self):
        """ Do the dull task of writing the fstab """
        strat = self.info.strategy
        disk = strat.disk

        appends = []

        ext4_ops = "rw,relatime,errors=remount-ro"

        for op in strat.get_operations():
            # TODO: Add custom mountpoints here!
            # Skip swap for GPT/UEFI
            if isinstance(op, DiskOpUseHome):
                huuid = get_part_uuid(op.home_part.path)
                fs = op.home_part_fs
                desc = "# {} at time of installation".format(op.home_part.path)
                i = "UUID={}\t/home\t{}\t{}\t0\t2"
                appends.append(desc)
                appends.append(i.format(huuid, fs, ext4_ops))
                continue
            elif isinstance(op, DiskOpCreateBoot):
                buuid = get_part_uuid(op.part.path)
                fs = op.fstype
                desc = "# {} at time of installation".format(op.part.path)
                i = "UUID={}\t/boot\t{}\t{}\t0\t2"
                appends.append(desc)
                appends.append(i.format(buuid, fs, ext4_ops))
                continue
            if disk.type == "gpt" and strat.is_uefi():
                continue

            # All swap handling from hereon out
            swap_path = None
            if isinstance(op, DiskOpCreateSwap):
                swap_path = op.part.path
            elif isinstance(op, DiskOpUseSwap):
                swap_path = op.swap_part.path

            if not swap_path:
                continue

            uuid = get_part_uuid(swap_path)
            if uuid:
                im = "UUID={}\tswap\tswap\tsw\t0\t0".format(uuid)
                appends.append(im)
            else:
                appends.append("{}\tswap\tswap\tsw\t0\t0".format(swap_path))

        # Add the root partition last
        root = strat.get_root_partition()
        uuid = get_part_uuid(root)
        appends.append("# {} at time of installation".format(root))

        appends.append("UUID={}\t/\text4\t{}\t0\t1".format(uuid, ext4_ops))

        fp = os.path.join(self.installer.get_installer_target_filesystem(),
                          "etc/fstab")

        try:
            with open(fp, "w") as fstab:
                fstab.write(FSTAB_HEADER.strip() + "\n")
                fstab.write("\n".join(appends) + "\n")
        except Exception as e:
            self.set_errors("Failed to write fstab: {}".format(e))
            return False
        return True


class PostInstallBootloader(PostInstallStep):
    """ Install the bootloader itself """

    # We record swap uuid into resume= parameter
    swap_uuid = None

    def __init__(self, info, installer):
        PostInstallStep.__init__(self, info, installer)

    def get_display_string(self):
        return "Configuring bootloader.. please wait"

    def apply(self):
        # Determine the swap path
        swap_path = None
        for op in self.info.strategy.get_operations():
            if isinstance(op, DiskOpCreateSwap):
                swap_path = op.part.path
            elif isinstance(op, DiskOpUseSwap):
                swap_path = op.swap_part.path

        if swap_path is not None:
            self.swap_uuid = get_part_uuid(swap_path)

        if self.info.strategy.is_uefi():
            return self.apply_uefi()
        return self.apply_bios()

    def is_long_step(self):
        """ UEFI no, GRUB yes. """
        return not self.info.strategy.is_uefi()

    def get_luks_uuid(self):
        """ Get the cached LUKS Container UUID """
        luks_uuid = None
        for op in self.info.strategy.get_operations():
            if isinstance(op, DiskOpCreateLUKSContainer):
                luks_uuid = op.crypto_uuid
                break
        return luks_uuid

    def is_encrypted_install(self):
        strategy = self.info.strategy
        if isinstance(strategy, EmptyDiskStrategy):
            if not strategy.use_lvm2:
                return False
            if not strategy.use_encryption:
                return False
        else:
            return False
        return True

    def is_lvm2_install(self):
        strategy = self.info.strategy
        if isinstance(strategy, EmptyDiskStrategy):
            if strategy.use_lvm2:
                return True
        return False

    def apply_boot_loader(self):
        """ Invoke clr-boot-manager itself """
        kdir = os.path.join(self.installer.get_installer_target_filesystem(),
                            "etc/kernel/cmdline.d")
        kresumefile = os.path.join(kdir, "10_resume.conf")

        # Write out the resume= parameter for clr-boot-manager
        if self.swap_uuid is not None:
            if not os.path.exists(kdir):
                try:
                    os.makedirs(kdir, 00755)
                    with open(kresumefile, "w") as kfile_output:
                        swap = "resume=UUID={}".format(self.swap_uuid)
                        kfile_output.write(swap)
                except Exception as ex:
                    self.set_errors("Error with kernel config: {}".format(ex))
                    return False

        cmd = "clr-boot-manager update"
        if not self.run_in_chroot(cmd):
            self.set_errors("Failed to update bootloader configuration")
            return False
        return True

    def apply_bios(self):
        """ Take the BIOS approach to bootloader configuration """
        if not self.info.bootloader_install:
            # Still need detecting from other distros
            return self.apply_boot_loader()
        cmd = "grub-install --force \"{}\"".format(self.info.bootloader_sz)
        if not self.run_in_chroot(cmd):
            self.set_errors("Failed to install GRUB bootloader")
            return False
        # Proxy back to CBM
        return self.apply_boot_loader()

    def apply_uefi(self):
        """ Take the UEFI approach to bootloader configuration
            TODO: In future this will be managed by clr-boot-manager itself,
            we're just ensuring that we write the EFI variables
        """
        # Proxy back to CBM
        if not self.apply_boot_loader():
            return False

        espt = self.installer.get_esp_target()
        ofile = os.path.join(self.get_efi_dir(espt),
                             "systemd/systemd-bootx64.efi")

        if os.path.exists(ofile):
            # Update the existing bootctl stuff, fallback to no nvvars mod
            commands = [
                "bootctl update --path=\"{}\"".format(espt),
                "bootctl update --path=\"{}\" --no-variables".format(espt),
                "bootctl install --path=\"{}\"".format(espt),
                "bootctl install --path=\"{}\" --no-variables".format(espt)
            ]
            # Install a fresh systemd-boot, fallback to no nvvars mod
        else:
            commands = [
                "bootctl install --path=\"{}\"".format(espt),
                "bootctl install --path=\"{}\" --no-variables".format(espt)
            ]

        updated_uefi = False
        for cmd in commands:
            try:
                subprocess.check_call(cmd, shell=True)
                updated_uefi = True
                break
            except:
                pass

        if not updated_uefi:
            self.set_errors("Failed to install systemd-boot")
            return False
        return True

    def get_ichild(self, root, child):
        t1 = os.path.join(root, child)
        if os.path.exists(t1) or not os.path.exists(root):
            return t1
        try:
            for i in os.listdir(root):
                i2 = i.lower()
                if i2 == child:
                    return os.path.join(root, i)
        except Exception as ex:
            print("Error obtaining {} dir: {}".format(child, ex))
        return t1

    def get_efi_dir(self, base):
        return self.get_ichild(base, "EFI")
