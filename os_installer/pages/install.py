#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
#  install.py - Installation progress page
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
from gi.repository import Gtk, Gdk, GObject
from basepage import BasePage
import threading

from os_installer.installer import Setup, InstallerEngine

class InstallationPage(BasePage):

    def __init__(self, installer):
        BasePage.__init__(self)

        self.label = Gtk.Label("")
        self.progress = Gtk.ProgressBar()

        self.pack_end(self.label, False, False, 0)
        self.pack_end(self.progress, False, False, 0)
        
        self.installer = installer
        self.engine = InstallerEngine()
        self.engine.set_progress_hook(self.update_progress)
        self.engine.set_error_hook(self.error_message)

        self.setup = Setup()
        self.should_pulse = False

    def go_quit(self):
        self.label.set_markup(_("Please close the window to exit the installer.\nYou just need to restart to start using your new operating system"))
        
    def error_message(self, message=""):
        self.critical_error_happened = True
        self.critical_error_message = message

    def update_progress(self, fail=False, done=False, pulse=False, total=0,current=0,message=""):
        if(pulse):
            Gdk.threads_enter()
            self.label.set_label(message)
            Gdk.threads_leave()
            self.do_progress_pulse(message)
            return
        if(done):
            # cool, finished :D
            self.should_pulse = False
            self.done = done
            Gdk.threads_enter()
            self.progress.set_fraction(1)
            self.label.set_label(message)
            GObject.idle_add(self.go_quit)
            Gdk.threads_leave()
            return
        self.should_pulse = False
        _total = float(total)
        _current = float(current)
        pct = float(_current/_total)
        szPct = int(pct)
        # thread block
        Gdk.threads_enter()
        self.progress.set_fraction(pct)
        self.label.set_label(message)
        Gdk.threads_leave()

        # end thread block

    def do_progress_pulse(self, message):
        def pbar_pulse():
            if(not self.should_pulse):
                return False
            Gdk.threads_enter()
            self.progress.pulse()
            Gdk.threads_leave()
            return self.should_pulse
        if(not self.should_pulse):
            self.should_pulse = True
            GObject.timeout_add(100, pbar_pulse)
        else:
            # asssume we're "pulsing" already
            self.should_pulse = True
            pbar_pulse()

    def install(self):
        try:
            if "esp" in self.installer.suggestions:
                self.engine.efi_mode = True
            self.engine.install(self.setup)
        except Exception, e:
            print e

    def prepare(self, pages=None):
        self.installer.can_go_back(False)
        self.installer.can_go_forward(False)

        for page in pages:
            page.seed(self.setup)
        print "Seeded"
        self.setup.print_setup()

        t = threading.Thread(target=self.install)
        t.start()

    def get_title(self):
        return _("Installing")

    def get_name(self):
        return "installing"

    def get_icon_name(self):
        return "install-symbolic"

    def is_hidden(self):
        return True
