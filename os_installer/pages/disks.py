#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
#  disks.py - Disk chooser
#  
#  Copyright (C) 2013-2015 Ikey Doherty <ikey@solus-project.com>
#  
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#  
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#  
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#  MA 02110-1301, USA.
#  
#
import gi.repository
from gi.repository import Gtk, GObject
from basepage import BasePage

import subprocess
import os
import commands
import parted
import string
from os_installer.installer import PartitionSetup


INDEX_PARTITION_PATH=0
INDEX_PARTITION_TYPE=1
INDEX_PARTITION_DESCRIPTION=2
INDEX_PARTITION_FORMAT_AS=3
INDEX_PARTITION_MOUNT_AS=4
INDEX_PARTITION_SIZE=5
INDEX_PARTITION_FREE_SPACE=6
INDEX_PARTITION_OBJECT=7

class DiskPanel(Gtk.HBox):

    def __init__(self, name):
        Gtk.HBox.__init__(self, 0, 10)

        # Need a shiny icon
        self.image = Gtk.Image()
        self.image.set_from_icon_name("drive-harddisk-symbolic", Gtk.IconSize.DIALOG)

        self.label = Gtk.Label(name)

        self.pack_start(self.image, False, False, 0)
        self.pack_start(self.label, False, True, 0)

        self.set_name('installer-box')

        self.device = name
        self.set_border_width(5)
        
class DiskPage(BasePage):

    def __init__(self, installer):
        BasePage.__init__(self)
        self.installer = installer

        # Hold our pages in a stack
        self.stack = Gtk.Stack()

        # Disk chooser page
        self.disks_page = Gtk.VBox()
        self.disks_page.set_margin_top(30)
        self.disks_page.set_border_width(20)
        self.listbox_disks = Gtk.ListBox()
        self.listbox_disks.get_style_context().add_class("no-bg")
        self.disks_page.pack_start(self.listbox_disks, True, True, 0)
        self.listbox_disks.connect("row-activated", self._disk_selected)

        self.stack.add_named(self.disks_page, "disks")
        
        # Partitioning page
        self.partition_page = Gtk.VBox()
        
        self.treeview = Gtk.TreeView()
        self.scroller = Gtk.ScrolledWindow(None, None)
        self.scroller.add(self.treeview)
        self.partition_page.set_border_width(12)
        self.scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroller.set_shadow_type(Gtk.ShadowType.ETCHED_IN)
        self.scroller.get_style_context().set_junction_sides(Gtk.JunctionSides.BOTTOM)
        self.partition_page.pack_start(self.scroller, True, True, 0)
        
        # device
        ren = Gtk.CellRendererText()
        self.column3 = Gtk.TreeViewColumn(_("Device"), ren)
        self.column3.add_attribute(ren, "markup", INDEX_PARTITION_PATH)
        self.treeview.append_column(self.column3)
        
        # Type
        ren = Gtk.CellRendererText()
        self.column4 = Gtk.TreeViewColumn(_("Type"), ren)
        self.column4.add_attribute(ren, "markup", INDEX_PARTITION_TYPE)
        self.treeview.append_column(self.column4)
        
        # description
        ren = Gtk.CellRendererText()
        self.column5 = Gtk.TreeViewColumn(_("Operating system"), ren)
        self.column5.add_attribute(ren, "markup", INDEX_PARTITION_DESCRIPTION)
        self.treeview.append_column(self.column5)
         
        # mount point
        ren = Gtk.CellRendererText()
        self.column6 = Gtk.TreeViewColumn(_("Mount point"), ren)
        self.column6.add_attribute(ren, "markup", INDEX_PARTITION_MOUNT_AS)
        self.treeview.append_column(self.column6)
        
        # format
        ren = Gtk.CellRendererText()
        self.column7 = Gtk.TreeViewColumn(_("Format?"), ren)
        self.column7.add_attribute(ren, "markup", INDEX_PARTITION_FORMAT_AS)        
        self.treeview.append_column(self.column7)
        
        # size
        ren = Gtk.CellRendererText()
        self.column8 = Gtk.TreeViewColumn(_("Size"), ren)
        self.column8.add_attribute(ren, "markup", INDEX_PARTITION_SIZE)
        self.treeview.append_column(self.column8)
        
        # Used space
        ren = Gtk.CellRendererText()
        self.column9 = Gtk.TreeViewColumn(_("Free space"), ren)
        self.column9.add_attribute(ren, "markup", INDEX_PARTITION_FREE_SPACE)
        self.treeview.append_column(self.column9)

        self.treeview.get_selection().connect("changed", self._partition_selected)
        
        toolbar = Gtk.Toolbar()
        toolbar.get_style_context().add_class(Gtk.STYLE_CLASS_INLINE_TOOLBAR)
        junctions = Gtk.JunctionSides.TOP
        toolbar.get_style_context().set_junction_sides(junctions)
        
        self.root = Gtk.ToolButton()
        self.root.set_label(_("Assign as root partition (ext4)"))
        self.root.set_is_important(True)
        self.root.set_sensitive(False)
        self.root.connect("clicked", self._assign_root)
        toolbar.add(self.root)

        self.swap = Gtk.ToolButton()
        self.swap.set_label(_("Assign as swap partition"))
        self.swap.set_is_important(True)
        self.swap.set_sensitive(False)
        self.swap.connect("clicked", self._assign_swap)
        toolbar.add(self.swap)

        sep = Gtk.SeparatorToolItem()
        sep.set_expand(True)
        sep.set_draw(False)
        toolbar.add(sep)
        
        gparted = Gtk.ToolButton()
        gparted.set_label(_("Launch Partition Editor"))
        gparted.connect("clicked", self._launch_gparted)
        gparted.set_is_important(True)
        toolbar.add(gparted)
        
        self.partition_page.pack_start(toolbar, False, False, 0)

        self.stack.add_named(self.partition_page, "partitions")

        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_UP_DOWN)
        self.pack_start(self.stack, True, True, 0)
        

        self.root_partition = None
        self.swap_partition = None

        GObject.idle_add(lambda: self.build_hdds())

    def _assign_root(self, btn):
        model = self.treeview.get_model()
        if self.root_partition is not None:
            # Already got a root set. Go fix.
            model.set_value(self.root_partition_row, INDEX_PARTITION_FORMAT_AS, self.root_format_saved)
            model.set_value(self.root_partition_row, INDEX_PARTITION_MOUNT_AS, self.root_mount_saved)
            
        self.root_partition_row = self.selected_row
        self.root_partition = self.selected_partition.partition
        self.root_partition_obj = self.selected_partition
        self.root_partition_obj.mount_as = "/"
        self.root_partition_obj.format_as = "ext4"

        self.root_format_saved = model[self.selected_row][INDEX_PARTITION_FORMAT_AS]
        self.root_mount_saved = model[self.selected_row][INDEX_PARTITION_MOUNT_AS]
        
        model.set_value(self.selected_row, INDEX_PARTITION_FORMAT_AS, "ext4")
        model.set_value(self.selected_row, INDEX_PARTITION_MOUNT_AS, "/")

        self.queue_draw()
        print "Assigned root (/) to %s" % self.root_partition.path

        self.installer.can_go_forward(True) # Only *really* need a root in alpha stages

    def _assign_swap(self, btn):
        model = self.treeview.get_model()
        if self.swap_partition is not None:
            # Already got a swap set. Go fix.
            model.set_value(self.swap_partition_row, INDEX_PARTITION_FORMAT_AS, self.root_format_saved)
            model.set_value(self.swap_partition_row, INDEX_PARTITION_MOUNT_AS, self.root_mount_saved)
            
        self.swap_partition_row = self.selected_row
        self.swap_partition = self.selected_partition.partition
        self.swap_partition_obj = self.selected_partition

        self.swap_format_saved = model[self.selected_row][INDEX_PARTITION_FORMAT_AS]
        self.swap_mount_saved = model[self.selected_row][INDEX_PARTITION_MOUNT_AS]
        
        model.set_value(self.selected_row, INDEX_PARTITION_FORMAT_AS, "swap")
        model.set_value(self.selected_row, INDEX_PARTITION_MOUNT_AS, "swap")

        self.queue_draw()
        print "Assigned swap to %s" % self.swap_partition.path
        
    def _launch_gparted(self, btn):
        os.system("gparted %s" % self.target_disk)
        self.installer.can_go_forward(False)
        self.build_partitions()
        self.build_esp()

    def _partition_selected(self, selection):
        model, treeiter = selection.get_selected()
        
        if treeiter == None:
            self.root.set_sensitive(False)
            self.swap.set_sensitive(False)
            return

        part = model[treeiter][INDEX_PARTITION_OBJECT]
        swap = part.type == "swap"
        self.root.set_sensitive(part.type != "" and not swap)
        self.swap.set_sensitive(part.type != "" and swap)

        self.selected_row = treeiter
        self.selected_partition = part
        
    def _disk_selected(self, box, row):
        device = row.get_children()[0].device
        self.target_disk = device
        self.build_partitions()
        self.stack.set_visible_child_name("partitions")
        
    def build_hdds(self):
        self.disks = []
        #model = Gtk.ListStore(str, str)            
        inxi = subprocess.Popen("inxi -c0 -D", shell=True, stdout=subprocess.PIPE)      
        for line in inxi.stdout:
            line = line.rstrip("\r\n")
            if(line.startswith("Disks:")):
                line = line.replace("Disks:", "")            
            sections = line.split(":")
            for section in sections:
                section = section.strip()
                if("/dev/" in section):                    
                    elements = section.split()
                    for element in elements:
                        if "/dev/" in element: 
                            self.disks.append(element)

        self.installer.suggestions["disks"] = self.disks
        self.build_esp()

        index = 0
        for disk in self.disks:
            panel = DiskPanel(disk)
            self.listbox_disks.add(panel)
            row = self.listbox_disks.get_row_at_index(index)
            row.set_name('disk-row')
            row.set_margin_bottom(5)
            index += 1
            panel.show_all()

    def build_esp(self):
        ''' Try to find an ESP '''
        if not os.path.exists("/sys/firmware/efi"):
            return
        esp = list()
        for path in self.disks:
            device = parted.getDevice(path)
            try:
                disk = parted.Disk(device)
            except Exception:
                pass
            if disk.type != "gpt":
                continue
            partition = disk.getFirstPartition()
            while (partition is not None):
                fs = partition.fileSystem
                if fs is not None:
                    if fs.type in ["fat", "fat32"]:
                        f = partition.getFlag(parted.PARTITION_BOOT)
                        if f:
                            if partition.path not in esp:
                                esp.append(partition.path)
                partition = partition.nextPartition()
        self.installer.suggestions["esp"] = esp

    def seed(self, setup):
        setup.target_disk = self.root_partition.path
        setup.partititons = list()
        setup.partitions.append(self.root_partition_obj)
        if self.swap_partition is not None:
            setup.partitions.append(self.swap_partition_obj)

    def build_partitions(self):
        os.popen('mkdir -p /tmp/os-installer/tmpmount')
        
        try:                                                                                            
            self.partitions = []
            
            model = Gtk.ListStore(str,str,str,str,str,str,str, object, bool, long, long, bool)
            model2 = Gtk.ListStore(str)
            
            swap_found = False
            
            if self.target_disk is not None:
                path =  self.target_disk # i.e. /dev/sda
                device = parted.getDevice(path)                
                try:
                    disk = parted.Disk(device)
                except Exception:
                    pass
                partition = disk.getFirstPartition()
                last_added_partition = PartitionSetup(partition)
                partition = partition.nextPartition()
                while (partition is not None):
                    if last_added_partition.partition.number == -1 and partition.number == -1:
                        last_added_partition.add_partition(partition)
                    else:                        
                        last_added_partition = PartitionSetup(partition)
                                        
                        if "swap" in last_added_partition.type:
                            last_added_partition.type = "swap"                                                            

                        if partition.number != -1 and "swap" not in last_added_partition.type and partition.type != parted.PARTITION_EXTENDED:
                            #Umount temp folder
                            if ('/tmp/os-installer/tmpmount' in commands.getoutput('mount')):
                                os.popen('umount /tmp/os-installer/tmpmount')

                            #Mount partition if not mounted
                            if (partition.path not in commands.getoutput('mount')):                                
                                os.system("mount %s /tmp/os-installer/tmpmount" % partition.path)

                            #Identify partition's description and used space
                            if (partition.path in commands.getoutput('mount')):
                                df_lines = commands.getoutput("df 2>/dev/null | grep %s" % partition.path).split('\n')
                                for df_line in df_lines:
                                    df_elements = df_line.split()
                                    if df_elements[0] == partition.path:
                                        last_added_partition.used_space = df_elements[4]  
                                        mount_point = df_elements[5]                              
                                        if "%" in last_added_partition.used_space:
                                            used_space_pct = int(last_added_partition.used_space.replace("%", "").strip())
                                            last_added_partition.free_space = int(float(last_added_partition.size) * (float(100) - float(used_space_pct)) / float(100))
                                        if os.path.exists(os.path.join(mount_point, 'etc/issue')):
                                            last_added_partition.description = commands.getoutput("cat " + os.path.join(mount_point, 'etc/issue')).replace('\\n', '').replace('\l', '').strip()
                                        if os.path.exists(os.path.join(mount_point, 'etc/evolveos-release')):
                                            last_added_partition.description = commands.getoutput("cat " + os.path.join(mount_point, 'etc/evolveos-release')).strip()                              
                                        if os.path.exists(os.path.join(mount_point, 'etc/lsb-release')):
                                            last_added_partition.description = commands.getoutput("cat " + os.path.join(mount_point, 'etc/lsb-release') + " | grep DISTRIB_DESCRIPTION").replace('DISTRIB_DESCRIPTION', '').replace('=', '').replace('"', '').strip()                                    
                                        if os.path.exists(os.path.join(mount_point, 'Windows/servicing/Version')):
                                            version = commands.getoutput("ls %s" % os.path.join(mount_point, 'Windows/servicing/Version'))                                    
                                            if version.startswith("6.1"):
                                                last_added_partition.description = "Windows 7"
                                            elif version.startswith("6.0"):
                                                last_added_partition.description = "Windows Vista"
                                            elif version.startswith("5.1") or version.startswith("5.2"):
                                                last_added_partition.description = "Windows XP"
                                            elif version.startswith("5.0"):
                                                last_added_partition.description = "Windows 2000"
                                            elif version.startswith("4.90"):
                                                last_added_partition.description = "Windows Me"
                                            elif version.startswith("4.1"):
                                                last_added_partition.description = "Windows 98"
                                            elif version.startswith("4.0.1381"):
                                                last_added_partition.description = "Windows NT"
                                            elif version.startswith("4.0.950"):
                                                last_added_partition.description = "Windows 95"
                                        elif os.path.exists(os.path.join(mount_point, 'Boot/BCD')):
                                            if os.system("grep -qs \"V.i.s.t.a\" " + os.path.join(mount_point, 'Boot/BCD')) == 0:
                                                last_added_partition.description = "Windows Vista bootloader"
                                            elif os.system("grep -qs \"W.i.n.d.o.w.s. .7\" " + os.path.join(mount_point, 'Boot/BCD')) == 0:
                                                last_added_partition.description = "Windows 7 bootloader"
                                            elif os.system("grep -qs \"W.i.n.d.o.w.s. .R.e.c.o.v.e.r.y. .E.n.v.i.r.o.n.m.e.n.t\" " + os.path.join(mount_point, 'Boot/BCD')) == 0:
                                                last_added_partition.description = "Windows recovery"
                                            elif os.system("grep -qs \"W.i.n.d.o.w.s. .S.e.r.v.e.r. .2.0.0.8\" " + os.path.join(mount_point, 'Boot/BCD')) == 0:
                                                last_added_partition.description = "Windows Server 2008 bootloader"
                                            else:
                                                last_added_partition.description = "Windows bootloader"
                                        elif os.path.exists(os.path.join(mount_point, 'Windows/System32')):
                                            last_added_partition.description = "Windows"
                                        break
                            else:
                                print "Failed to mount %s" % partition.path

                            
                            #Umount temp folder
                            if ('/tmp/os-installer/tmpmount' in commands.getoutput('mount')):
                                os.popen('umount /tmp/os-installer/tmpmount')
                                
                    if last_added_partition.size > 1.0:
                        if last_added_partition.partition.type == parted.PARTITION_LOGICAL:
                            display_name = "  " + last_added_partition.name
                        else:
                            display_name = last_added_partition.name

                        iter = model.append([display_name, last_added_partition.type, last_added_partition.description, "", "", '%.0f' % round(last_added_partition.size, 0), str(last_added_partition.free_space), last_added_partition, False, last_added_partition.start, last_added_partition.end, False]);
                        if last_added_partition.partition.number == -1:                     
                            model.set_value(iter, INDEX_PARTITION_TYPE, "<span foreground='#a9a9a9'>%s</span>" % last_added_partition.type)                                    
                        elif last_added_partition.partition.type == parted.PARTITION_EXTENDED:                    
                            model.set_value(iter, INDEX_PARTITION_TYPE, "<span foreground='#a9a9a9'>%s</span>" % _("Extended"))  
                        else:                                        
                            if last_added_partition.type == "ntfs":
                                color = "#42e5ac"
                            elif last_added_partition.type == "fat32":
                                color = "#18d918"
                            elif last_added_partition.type == "ext4":
                                color = "#4b6983"
                            elif last_added_partition.type == "ext3":
                                color = "#7590ae"
                            elif last_added_partition.type in ["linux-swap", "swap"]:
                                color = "#c1665a"
                                last_added_partition.mount_as = "swap"
                                model.set_value(iter, INDEX_PARTITION_MOUNT_AS, "swap")
                            else:
                                color = "#a9a9a9"
                            model.set_value(iter, INDEX_PARTITION_TYPE, "<span foreground='%s'>%s</span>" % (color, last_added_partition.type))                                            
                            #deviceSize = float(device.getSize()) * float(0.9) # Hack.. reducing the real size to 90% of what it is, to make sure our partitions fit..
                            #space = int((float(partition.getSize()) / deviceSize) * float(80))                            
                            self.partitions.append(last_added_partition)
                            
                    partition = partition.nextPartition()
            self.treeview.set_model(model)
        except Exception, e:
            print e
        self.build_esp()
            
    def prepare(self):
        self.installer.can_go_back(True)
        self.installer.can_go_forward(self.root_partition is not None)
        
    def get_title(self):
        return _("Where should we install?")

    def get_name(self):
        return "disks"

    def get_icon_name(self):
        return "drive-harddisk-system-symbolic"

    def get_primary_answer(self):
        answer =  _("Format %s as %s for root (/)") % (self.root_partition.path, "ext4")
        if self.swap_partition is not None:
            answer += "\n" + _("Format and use %s as swap device") % self.swap_partition.path
        return answer
