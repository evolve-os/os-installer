import os
import subprocess
from subprocess import Popen
import time
import shutil
import gettext
import stat
import commands
import sys
import parted
from configobj import ConfigObj

from resources import RESOURCE_DIR

gettext.install("osinstaller", "/usr/share/locale")


class InstallerEngine:
    ''' This is central to the live installer '''

    efi_mode = False

    def __init__(self):
        self.conf_file = '/etc/os-installer/install.conf'
        configuration = ConfigObj(self.conf_file)     
        self.live_user = configuration['Configuration']['LiveUser']

        self.media1 = "/run/initramfs/live/LiveOS/squashfs.img"
        self.media_type1 = "squashfs"
        self.media2 = "/source1/LiveOS/rootfs.img"
        self.media_type2 = "ext4"

    def set_progress_hook(self, progresshook):
        ''' Set a callback to be called on progress updates '''
        ''' i.e. def my_callback(progress_type, message, current_progress, total) '''
        ''' Where progress_type is any off PROGRESS_START, PROGRESS_UPDATE, PROGRESS_COMPLETE, PROGRESS_ERROR '''
        self.update_progress = progresshook
        
    def set_error_hook(self, errorhook):
        ''' Set a callback to be called on errors '''
        self.error_message = errorhook

    def get_distribution_name(self):
        return self.distribution_name

    def get_distribution_version(self):
        return self.distribution_version
        
    def step_format_partitions(self, setup):        
        for partition in setup.partitions:                    
            if(partition.format_as is not None and partition.format_as != ""):                
                # report it. should grab the total count of filesystems to be formatted ..
                self.update_progress(total=5, current=1, pulse=True, message=_("Formatting %(partition)s as %(format)s..." % {'partition':partition.partition.path, 'format':partition.format_as}))
                
                #Format it
                if partition.format_as == "swap":
                    cmd = "mkswap %s" % partition.partition.path
                else:
                    if (partition.format_as == "jfs"):
                        cmd = "mkfs.%s -q %s" % (partition.format_as, partition.partition.path)
                    elif (partition.format_as == "xfs"):
                        cmd = "mkfs.%s -f %s" % (partition.format_as, partition.partition.path)
                    elif (partition.format_as in ["ext", "ext3", "ext4"]):
                        cmd = "mkfs.%s -F %s" % (partition.format_as, partition.partition.path)
                    elif (partition.format_as == "btrfs"):
                        cmd = "mkfs.%s -f %s" % (partition.format_as, partition.partition.path)
                    else:
                        cmd = "mkfs.%s %s" % (partition.format_as, partition.partition.path) # works with bfs, minix, msdos, ntfs, vfat
					
                print "EXECUTING: '%s'" % cmd
                p = Popen(cmd, shell=True)
                p.wait() # this blocks
                partition.type = partition.format_as
                                        
    def step_mount_partitions(self, setup):
        # Mount the installation media
        print " --> Mounting partitions"

        # Mount the squashfs.img
        self.update_progress(total=5, current=2, message=_("Mounting %(partition)s on %(mountpoint)s") % {'partition':self.media1, 'mountpoint':"/source1/"})
        print " ------ Mounting %s on %s" % (self.media1, "/source1/")
        self.do_mount(self.media1, "/source1/", self.media_type1, options="loop")

        # Mount the rootfs.img from inside squashfs.img
        self.update_progress(total=5, current=3, message=_("Mounting %(partition)s on %(mountpoint)s") % {'partition':self.media2, 'mountpoint':"/source/"})
        print " ------ Mounting %s on %s" % (self.media2, "/source/")
        self.do_mount(self.media2, "/source/", self.media_type2, options="loop")
                
        # Mount the target partition
        for partition in setup.partitions:                    
            if(partition.mount_as is not None and partition.mount_as != ""):   
                  if partition.mount_as == "/":
                        self.update_progress(total=5, current=5, message=_("Mounting %(partition)s on %(mountpoint)s") % {'partition':partition.partition.path, 'mountpoint':"/target/"})
                        print " ------ Mounting %s on %s" % (partition.partition.path, "/target/")
                        self.do_mount(partition.partition.path, "/target", partition.type, None)
                        break
        
        # Mount the other partitions        
        for partition in setup.partitions:
            if(partition.mount_as is not None and partition.mount_as != "" and partition.mount_as != "/" and partition.mount_as != "swap"):
                print " ------ Mounting %s on %s" % (partition.partition.path, "/target" + partition.mount_as)
                os.system("mkdir -p /target" + partition.mount_as)
                self.do_mount(partition.partition.path, "/target" + partition.mount_as, partition.type, None)

        if self.efi_mode and setup.grub_device is not None:
            tgt = "/target/boot/efi"
            if not os.path.exists(tgt):
                os.makedirs(tgt)
            self.do_mount(setup.grub_device, "/target/boot/efi", "vfat", None)

    def get_uuid(self, path):
        partition_uuid = path
        try:
            blkid = commands.getoutput('blkid').split('\n')
            for blkid_line in blkid:
                blkid_elements = blkid_line.split(':')
                if blkid_elements[0] == path:
                    blkid_mini_elements = blkid_line.split()
                    for blkid_mini_element in blkid_mini_elements:
                        if "UUID=" in blkid_mini_element:
                            partition_uuid = blkid_mini_element.replace('"', '').strip()
                            break
                    break
        except Exception, detail:
            print detail
        return partition_uuid

    def install(self, setup):        
        # mount the media location.
        print " --> Installation started"
        try:
            if(not os.path.exists("/target")):
                os.mkdir("/target")
            if(not os.path.exists("/source")):
                os.mkdir("/source")
            if(not os.path.exists("/source1")):
                os.mkdir("/source1")
            # find the squashfs..
            if(not os.path.exists(self.media1)):
                print "Base filesystem does not exist! Critical error (exiting)."
                sys.exit(1) # change to report
       
            self.step_format_partitions(setup)
            self.step_mount_partitions(setup)                        
            
            # walk root filesystem
            SOURCE = "/source/"
            DEST = "/target/"
            directory_times = []
            our_total = 0
            our_current = -1
            os.chdir(SOURCE)
            # index the files
            print " --> Indexing files"
            for top,dirs,files in os.walk(SOURCE, topdown=False):
                our_total += len(dirs) + len(files)
                self.update_progress(pulse=True, message=_("Indexing files to be copied.."))
            our_total += 1 # safenessness
            print " --> Copying files"
            for top,dirs,files in os.walk(SOURCE):
                # Sanity check. Python is a bit schitzo
                dirpath = top
                if(dirpath.startswith(SOURCE)):
                    dirpath = dirpath[len(SOURCE):]
                for name in dirs + files:
                    # following is hacked/copied from Ubiquity
                    rpath = os.path.join(dirpath, name)
                    sourcepath = os.path.join(SOURCE, rpath)
                    targetpath = os.path.join(DEST, rpath)
                    st = os.lstat(sourcepath)
                    mode = stat.S_IMODE(st.st_mode)

                    # now show the world what we're doing                    
                    our_current += 1
                    self.update_progress(total=our_total, current=our_current, message=_("Copying %s" % rpath))

                    if os.path.exists(targetpath):
                        if not os.path.isdir(targetpath):
                            os.remove(targetpath)                        
                    if stat.S_ISLNK(st.st_mode):
                        if os.path.lexists(targetpath):
                            os.unlink(targetpath)
                        linkto = os.readlink(sourcepath)
                        os.symlink(linkto, targetpath)
                    elif stat.S_ISDIR(st.st_mode):
                        if not os.path.isdir(targetpath):
                            os.mkdir(targetpath, mode)
                    elif stat.S_ISCHR(st.st_mode):                        
                        os.mknod(targetpath, stat.S_IFCHR | mode, st.st_rdev)
                    elif stat.S_ISBLK(st.st_mode):
                        os.mknod(targetpath, stat.S_IFBLK | mode, st.st_rdev)
                    elif stat.S_ISFIFO(st.st_mode):
                        os.mknod(targetpath, stat.S_IFIFO | mode)
                    elif stat.S_ISSOCK(st.st_mode):
                        os.mknod(targetpath, stat.S_IFSOCK | mode)
                    elif stat.S_ISREG(st.st_mode):
                        # we don't do blacklisting yet..
                        try:
                            os.unlink(targetpath)
                        except:
                            pass
                        self.do_copy_file(sourcepath, targetpath)
                    os.lchown(targetpath, st.st_uid, st.st_gid)
                    if not stat.S_ISLNK(st.st_mode):
                        os.chmod(targetpath, mode)
                    if stat.S_ISDIR(st.st_mode):
                        directory_times.append((targetpath, st.st_atime, st.st_mtime))
                    # os.utime() sets timestamp of target, not link
                    elif not stat.S_ISLNK(st.st_mode):
                        os.utime(targetpath, (st.st_atime, st.st_mtime))
                # Apply timestamps to all directories now that the items within them
                # have been copied.
            print " --> Restoring meta-info"
            for dirtime in directory_times:
                (directory, atime, mtime) = dirtime
                try:
                    self.update_progress(pulse=True, message=_("Restoring meta-information on %s" % directory))
                    os.utime(directory, (atime, mtime))
                except OSError:
                    pass
                    
            # Steps:
            our_total = 6
            our_current = 0
            # chroot
            print " --> Chrooting"
            self.update_progress(total=our_total, current=our_current, message=_("Entering new system.."))            
            os.system("mount --bind /dev/ /target/dev/")
            os.system("mount --bind /dev/shm /target/dev/shm")
            os.system("mount --bind /dev/pts /target/dev/pts")
            os.system("mount --bind /sys/ /target/sys/")
            os.system("mount --bind /proc/ /target/proc/")
            os.system("cp -f /etc/resolv.conf /target/etc/resolv.conf")
                                          
            # remove live user
            print " --> Removing live user"
            live_user = self.live_user
            our_current += 1
            self.update_progress(total=our_total, current=our_current, message=_("Removing live configuration (user)"))
            self.do_run_in_chroot("userdel -r %s" % live_user)
            # can happen
            if(os.path.exists("/target/home/%s" % live_user)):
                self.do_run_in_chroot("rm -rf /home/%s" % live_user)
            # Our overriden default 
            if os.path.exists("/target/var/lib/AccountsService/users/%s" % live_user):
                self.do_run_in_chroot("rm -f /var/lib/AccountsService/users/%s" % live_user)

            # Probably SolusOS specific, remove live from sudoers
            self.do_run_in_chroot("sed -e '/live ALL=/d' -i /etc/sudoers")

            # systemd specific, initialize a new machine id
            our_current += 1
            self.update_progress(total=our_total, current=our_current, message=_("Initializing the new installation"))
            self.do_run_in_chroot("rm /etc/machine-id")
            self.do_run_in_chroot("systemd-machine-id-setup")

            if os.path.exists("/target/etc/gdm"):
                gdm_source = os.path.join(RESOURCE_DIR, "gdm.conf")
                gdm_target = "/target/etc/gdm/custom.conf"
                try:
                    shutil.copy2(gdm_source, gdm_target)
                except Exception, e:
                    print("GDM: %s" % e)
                    pass

            # Again SolusOS specific, but remove the installer from the image
            # We need to get the configuration done via dbus eventually.
            our_current += 1
            self.update_progress(total=our_total, current=our_current, message=_("Removing live configuration (installer)"))
            self.do_run_in_chroot("eopkg remove os-installer --ignore-comar")

            # Disable direct use of root account
            self.do_run_in_chroot("passwd -d root")
            
            # write the /etc/fstab
            print " --> Writing fstab"
            our_current += 1
            self.update_progress(total=our_total, current=our_current, message=_("Writing filesystem mount information"))
            # make sure fstab has default /proc and /sys entries
            if(not os.path.exists("/target/etc/fstab")):
                os.system("echo \"#### Static Filesystem Table File\" > /target/etc/fstab")
            fstab = open("/target/etc/fstab", "a")
            fstab.write("proc\t/proc\tproc\tdefaults\t0\t0\n")
            for partition in setup.partitions:
                if (partition.mount_as is not None and partition.mount_as != "None":
                    partition_uuid = self.get_uuid(partition.partition.path)
                                        
                    fstab.write("# %s\n" % (partition.partition.path))                            
                    
                    if(partition.mount_as == "/"):
                        fstab_fsck_option = "1"
                        self.root_partition = partition_uuid
                    else:
                        fstab_fsck_option = "0" 
                                            
                    if("ext" in partition.type):
                        fstab_mount_options = "rw,errors=remount-ro"
                    else:
                        fstab_mount_options = "defaults"

                    if partition.type == "swap":
                        # systemd's gpt generator automounts these guys
                        if partition.partition.disk is not None and partition.partition.disk.type == "gpt":
                            continue
                        fstab.write("%s\tswap\tswap\tsw\t0\t0\n" % partition_uuid)
                    else:
                        fstab.write("%s\t%s\t%s\t%s\t%s\t%s\n" % (partition_uuid, partition.mount_as, partition.type, fstab_mount_options, "0", fstab_fsck_option))
            if self.efi_mode and setup.grub_device is not None:
                fstab.write("%s\t/boot/efi\tvfat\tdefaults\t0\t0\n" % self.get_uuid(setup.grub_device))
            fstab.close()
            
            # write host+hostname infos
            print " --> Writing hostname"
            our_current += 1
            self.update_progress(total=our_total, current=our_current, message=_("Setting hostname"))
            hostnamefh = open("/target/etc/hostname", "w")
            hostnamefh.write("%s\n" % setup.hostname)
            hostnamefh.close()
            hostsfh = open("/target/etc/hosts", "w")
            hostsfh.write("127.0.0.1\tlocalhost\n")
            hostsfh.write("127.0.1.1\t%s\n" % setup.hostname)
            hostsfh.write("# The following lines are desirable for IPv6 capable hosts\n")
            hostsfh.write("::1     localhost ip6-localhost ip6-loopback\n")
            hostsfh.write("fe00::0 ip6-localnet\n")
            hostsfh.write("ff00::0 ip6-mcastprefix\n")
            hostsfh.write("ff02::1 ip6-allnodes\n")
            hostsfh.write("ff02::2 ip6-allrouters\n")
            hostsfh.write("ff02::3 ip6-allhosts\n")
            hostsfh.close()
            
            # write MBR (grub)
            print " --> Configuring bootloader"
            our_current += 1
            if(setup.grub_device is not None):
                self.update_progress(pulse=True, total=our_total, current=our_current, message=_("Installing bootloader"))
                if self.efi_mode:
                    print " --> Installing goofiboot"
                    self.do_goofi(our_total, our_current)
                else:
                    print " --> Running grub-install"
                    self.do_run_in_chroot("grub-install --force %s" % setup.grub_device)
                    self.do_configure_grub(our_total, our_current)
            
            # now unmount it
            print " --> Unmounting partitions"
            try:
                os.system("sync")
                if self.efi_mode and setup.grub_device is not None:
                    os.system("umount --force /target/boot/efi")
                os.system("umount --force /target/dev/shm")
                os.system("umount --force /target/dev/pts")
                os.system("umount --force /target/dev/")
                os.system("umount --force /target/sys/")
                os.system("umount --force /target/proc/")
                os.system("rm -rf /target/etc/resolv.conf")
                for partition in setup.partitions:
                    if(partition.mount_as is not None and partition.mount_as != "" and partition.mount_as != "/" and partition.mount_as != "swap"):
                        self.do_unmount("/target" + partition.mount_as)
                self.do_unmount("/target")
                self.do_unmount("/source")
                self.do_unmount("/source1")
            except Exception, detail:
                #best effort, no big deal if we can't umount something
                print detail 

            self.update_progress(done=True, message=_("Installation finished"))
            print " --> All done"
            
        except Exception:            
            import traceback
            exc_type, exc_value, exc_traceback = sys.exc_info()
            traceback.print_tb(exc_traceback, limit=1, file=sys.stdout)
    
    def do_run_in_chroot(self, command):
        os.system("chroot /target/ /bin/sh -c \"%s\"" % command)
        
    def do_configure_grub(self, our_total, our_current):
        self.update_progress(pulse=True, total=our_total, current=our_current, message=_("Configuring bootloader"))
        print " --> Running grub-mkconfig"
        self.do_run_in_chroot("grub-mkconfig -o /boot/grub/grub.cfg")
        grub_output = commands.getoutput("chroot /target/ /bin/sh -c \"grub-mkconfig -o /boot/grub/grub.cfg\"")
        grubfh = open("/var/log/os-installer-grub-output.log", "w")
        grubfh.writelines(grub_output)
        grubfh.close()


    def get_ichild(self, root,child):
        t1 = os.path.join(root, child)
        if os.path.exists(t1) or not os.path.exists(root):
            return t1
        try:
            for i in os.listdir(root):
                i2 = i.lower()
                if i2 == child:
                    return os.path.join(root, i)
        except Exception, ex:
            print("Error obtaining %s dir: %s" % (child, ex))
        return t1

    def get_efi_dir(self, base):
        return self.get_ichild(base, "EFI")

    def get_loader_dir(self, base):
        return self.get_ichild(base, "loader")

    def get_efi_boot_dir(self, base):
        return self.get_ichild(self.get_efi_dir(base), "Boot")

    def get_efi_boot_file(self, base):
        return self.get_ichild(self.get_efi_boot_dir(base), "BOOTX64.EFI")

    def get_loader_entries(self, base):
        return self.get_ichild(self.get_loader_dir(base), "entries")

    def get_solus_dir(self, base):
        return self.get_ichild(base, "solus")

    def do_goofi(self, our_total, our_current):
        self.update_progress(pulse=True, total=our_total, current=our_current, message=_("Configuring bootloader"))
        tgt = self.get_efi_boot_file("/target/boot/efi")

        # Sanity
        if not os.path.exists("/target/boot/efi"):
            try:
                os.makedirs("/target/boot/efi")
            except Exception, e:
                print("Unable to make dirs: %s" % e)
                return

        # Ensure they get efivars too
        cmd = "goofiboot install --path=%s" % "/target/boot/efi"
        retcode = 0
        try:
            p = Popen(cmd, shell=True)
            p.wait()
            retcode = p.returncode
        except Exception, e:
            print("Failed to install goofiboot: %s" % e)
            return
        if retcode != 0:
            print("Failed to install goofiboot")
            return

        # Set the default entry
        entfile = os.path.join(self.get_loader_dir("/target/boot/efi"), "loader.conf")
        if not os.path.exists(entfile):
            dirn = self.get_loader_dir("/target/boot/efi")
            if not os.path.exists(dirn):
                os.makedirs(dirn)
            with open(entfile, "w") as defconf:
                defconf.write("default solus\ntimeout 4\n")

        # Write the Solus entry
        solfile = "/target/boot/efi/loader/entries/solus.conf"
        if not os.path.exists(os.path.dirname(solfile)):
            os.makedirs(os.path.dirname(solfile))
        with open(solfile, "w") as solconf:
            solconf.write("title Solus Operating System\nlinux /solus/kernel\ninitrd /solus/initramfs\noptions root=%s quiet\n" % self.root_partition)

        # Now install the Solus kernel/initramfs.
        kver = os.uname()[2]
        sdir = self.get_solus_dir("/target/boot/efi")
        if not os.path.exists(sdir):
            os.makedirs(sdir)
        kernel = "/source/boot/kernel-%s" % kver
        initrd = "/source/boot/initramfs-%s.img" % kver
        tkernel = os.path.join(sdir, "kernel")
        tinitrd = os.path.join(sdir, "initramfs")
        if os.path.exists(tkernel):
            print "Removing %s" % tkernel
        if os.path.exists(tinitrd):
            print "Removing %s" % tinitrd
        shutil.copy(kernel, tkernel)
        shutil.copy(initrd, tinitrd)


    def do_mount(self, device, dest, type, options=None):
        ''' Mount a filesystem '''
        p = None
        if(options is not None):
            cmd = "mount -o %s -t %s %s %s" % (options, type, device, dest)            
        else:
            cmd = "mount -t %s %s %s" % (type, device, dest)
        print "EXECUTING: '%s'" % cmd
        p = Popen(cmd ,shell=True)        
        p.wait()
        return p.returncode

    def do_unmount(self, mountpoint):
        ''' Unmount a filesystem '''
        cmd = "umount %s" % mountpoint
        print "EXECUTING: '%s'" % cmd
        p = Popen(cmd, shell=True)
        p.wait()
        return p.returncode

    def do_copy_file(self, source, dest):
        # TODO: Add md5 checks. BADLY needed..
        BUF_SIZE = 16 * 1024
        input = open(source, "rb")
        dst = open(dest, "wb")
        while(True):
            read = input.read(BUF_SIZE)
            if not read:
                break
            dst.write(read)
        input.close()
        dst.close()
        
        
# Represents the choices made by the user
class Setup(object):
    partitions = [] #Array of PartitionSetup objects
    hostname = None 
    grub_device = None
    target_disk = None
    
    def print_setup(self):
        print "-------------------------------------------------------------------------"
        print "hostname: %s " % self.hostname
        print "grub_device: %s " % self.grub_device
        print "target_disk: %s " % self.target_disk
        print "partitions:"
        for partition in self.partitions:
            partition.print_partition()
        print "-------------------------------------------------------------------------"
    
class PartitionSetup(object):
    name = ""    
    type = ""
    format_as = None
    mount_as = None    
    partition = None
    aggregatedPartitions = []

    def __init__(self, partition):
        self.partition = partition
        self.size = partition.getSize()
        self.start = partition.geometry.start
        self.end = partition.geometry.end
        self.description = ""
        self.used_space = ""
        self.free_space = ""

        if partition.number != -1:
            self.name = partition.path            
            if partition.fileSystem is None:
                # no filesystem, check flags
                if partition.type == parted.PARTITION_SWAP:
                    self.type = ("Linux swap")
                elif partition.type == parted.PARTITION_RAID:
                    self.type = ("RAID")
                elif partition.type == parted.PARTITION_LVM:
                    self.type = ("Linux LVM")
                elif partition.type == parted.PARTITION_HPSERVICE:
                    self.type = ("HP Service")
                elif partition.type == parted.PARTITION_PALO:
                    self.type = ("PALO")
                elif partition.type == parted.PARTITION_PREP:
                    self.type = ("PReP")
                elif partition.type == parted.PARTITION_MSFT_RESERVED:
                    self.type = ("MSFT Reserved")
                elif partition.type == parted.PARTITION_EXTENDED:
                    self.type = ("Extended Partition")
                elif partition.type == parted.PARTITION_LOGICAL:
                    self.type = ("Logical Partition")
                elif partition.type == parted.PARTITION_FREESPACE:
                    self.type = ("Free Space")
                else:
                    self.type =("Unknown")
            else:
                self.type = partition.fileSystem.type
        else:
            self.type = ""
            self.name = _("unallocated")

    def add_partition(self, partition):
        self.aggregatedPartitions.append(partition)
        self.size = self.size + partition.getSize()
        self.end = partition.geometry.end
    
    def print_partition(self):
        print "Device: %s, format as: %s, mount as: %s" % (self.partition.path, self.format_as, self.mount_as)
