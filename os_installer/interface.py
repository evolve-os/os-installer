#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
#  interface.py - Main Installer UI
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
from gi.repository import Gtk, Gdk, Pango
from live_page import LivePage
from installer_section import InstallerSection
from resources import *
import os


class InstallerWindow(Gtk.Window):

    def rowsel(self, box, row):
        page = self.rows[row]
        self.stack.set_visible_child_name(page)

    def go_home(self):
        self.stack.set_visible_child_name("intro")

    def __init__(self):
        Gtk.Window.__init__(self)
        self.connect("destroy", Gtk.main_quit)

        self.set_size_request (700, 500)
        self.set_position (Gtk.WindowPosition.CENTER)
        self.set_title(_("Installer"))
        self.set_icon_name("system-software-install")
        self._init_theme()


        boxen = Gtk.HeaderBar()
        boxen.set_show_close_button(True)
        boxen.set_title(self.get_title())
        self.set_titlebar(boxen)

        self.layout = Gtk.VBox()

        self.add(self.layout)

        self.stack = Gtk.Stack()
        self.stack.add_named(self.create_intro_page(), "intro")
        self.stack.add_named(InstallerSection(), "install")
        self.stack.add_named(LivePage(), "live")

        self.listbox.connect("row-activated", self.rowsel)
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.layout.add(self.stack)

        self.set_resizable(False)
        self.show_all()

    def _init_theme(self):
        # TEMPORARY: Needs to be read from config
        theme = config[UI_THEME]
        self.get_settings().set_string_property("gtk-icon-theme-name", theme["IconTheme"], "0")
        self.get_settings().set_string_property("gtk-theme-name", theme["Widgets"], "Adwaita")
        self.use_symbolic = theme["SymbolicIcons"].lower() == "true"

        if theme["DarkControls"].lower() == "true":
            self.get_settings().set_property("gtk-application-prefer-dark-theme", True)

        context = self.get_style_context()
        css_provider = Gtk.CssProvider()
        css_provider.load_from_path('%s/styling.css' % RESOURCE_DIR)
        screen = Gdk.Screen.get_default()
        context.add_provider_for_screen(screen, css_provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)

    def create_intro_page(self):
        layout = Gtk.VBox()
        # Create a pretty label
        label = "<span font=\"30.5\" color=\"#82807b\">%s</span>" % DISTRO_NAME
        label_widg = Gtk.Label(label)
        label_widg.set_use_markup(True)
        label_widg.set_halign(Gtk.Align.CENTER)

        header = Gtk.HBox()
        layout.pack_start(header, False, True, 0)

        layout.pack_start(label_widg, True, True, 0)        

        self.listbox = Gtk.ListBox()
        self.rows = dict()

        row = Gtk.HBox(5)
        button = self.nice_button("Install Solus", "installsolus192.png")
        row.pack_start(button, False, False, 0)
        button.connect("clicked", lambda x: self.stack.set_visible_child_name("install"))
        button = self.nice_button("Continue using the live preview", "livepreview192.png")
        button.connect("clicked", lambda x: self.stack.set_visible_child_name("live"))
        row.pack_start(button, False, False, 0)

        layout.pack_end(row, True, True, 0)

        return layout

    def nice_button(self, text, icon):
        btn = Gtk.Button()
        box = Gtk.VBox(0)
        btn.add(box)
        img = Gtk.Image.new_from_file(os.path.join(RESOURCE_DIR, icon))
        lab = Gtk.Label(text)
        box.pack_start(img, False, False, 0)
        box.pack_start(lab, False, False, 0)
        btn.set_relief(Gtk.ReliefStyle.NONE)
        btn.set_can_focus(False)
        return btn
