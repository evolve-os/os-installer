#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
#  system.py - System options
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
from gi.repository import Gtk
from basepage import BasePage
import re

ValidHostnameRegex = \
"^(([a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9\-]*[a-zA-Z0-9])\.)*([A-Za-z0-9]|[A-Za-z0-9][A-Za-z0-9\-]*[A-Za-z0-9])$";

class SystemPage(BasePage):

    def __init__(self, installer):
        BasePage.__init__(self)
        self.installer = installer
        self.install_grub = False
        self.hostname = None

        content = Gtk.VBox()
        content.set_border_width(30)
        self.add(content)
        
        # hostname section
        host = Gtk.Frame()
        host.set_label(_("What name should this computer use on the network?"))
        content.pack_start(host, False, False, 10)

        self.host_entry = Gtk.Entry()
        self.host_entry.set_placeholder_text(_("Type the hostname here"))
        self.host_regex = re.compile(ValidHostnameRegex)
        self.host_entry.connect("changed", self.host_validate)

        host_wrap = Gtk.VBox()
        host_wrap.set_border_width(5)
        host_wrap.add(self.host_entry)
        host.add(host_wrap)

        # grub
        grub_frame = Gtk.Frame()
        grub_check = Gtk.CheckButton(_("Should we install a boot loader on this computer?"))
        grub_frame.set_label_widget(grub_check)

        self.grub_combo = Gtk.ComboBox()
        renderer = Gtk.CellRendererText ()
        self.grub_combo.pack_start (renderer, True)
        self.grub_combo.add_attribute (renderer, "text", 0)
        
        grub_wrap = Gtk.VBox()
        grub_wrap.set_border_width(5)
        grub_wrap.add(self.grub_combo)
        grub_frame.add(grub_wrap)

        # Hook up the checkbutton
        grub_check.connect("clicked", lambda x: self.grub_combo.set_sensitive(x.get_active()))
        self.grub_combo.set_sensitive(False)
        
        content.pack_start(grub_frame, False, False, 10)
                
        self.installer.can_go_forward(False)

        self.grub_model = None

    def host_validate(self, entry):
        text = entry.get_text()
        match = self.host_regex.match(text)
        if match is None:
            self.installer.can_go_forward(False)
            entry.set_icon_from_icon_name(Gtk.EntryIconPosition.SECONDARY, None)
            self.hostname = None
        else:
            entry.set_icon_from_icon_name(Gtk.EntryIconPosition.SECONDARY, "emblem-ok-symbolic")
            self.installer.can_go_forward(True)
            self.hostname = text

    def prepare(self):
        if self.grub_model is None:
            self.grub_model = Gtk.ListStore(str)
            disks = None
            if "esp" in self.installer.suggestions:
                disks = self.installer.suggestions["esp"]
            else:
                disks = self.installer.suggestions["disks"]
            for disk in disks:
                self.grub_model.append([disk])
            self.grub_combo.set_model(self.grub_model)
            self.grub_combo.set_active(0)
            
        self.installer.can_go_back(True)
        self.installer.can_go_forward(self.hostname is not None)
        
    def get_title(self):
        return _("System settings")

    def get_name(self):
        return "system"

    def get_icon_name(self):
        return "preferences-system-symbolic"

    def seed(self, setup):
        setup.hostname = self.hostname
        if self.grub_combo.is_sensitive():
            setup.grub_device = self.grub_model[self.grub_combo.get_active()][0]
        else:
            setup.grub_device = None

    def get_primary_answer(self):
        answer =  _("Computer host name set to %s") % self.hostname
        if self.grub_combo.is_sensitive():
            grub_device = self.grub_model[self.grub_combo.get_active()][0]
            answer += "\n" + _("Install bootloader to %s") % grub_device
        return answer
