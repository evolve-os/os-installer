#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
#  basepage.py - Provides base for other Installer pages
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

        
class BasePage(Gtk.VBox):

    def __init__(self):
        Gtk.VBox.__init__(self)
        self.set_border_width(10)

        self.title = Gtk.Label("<span font=\"20.5\" color=\"#82807b\">%s</span>" % self.get_title())
        self.title.set_use_markup(True)
        
        self.image = Gtk.Image()
        self.image.set_from_icon_name(self.get_icon_name(), Gtk.IconSize.DIALOG)
        self.image.set_padding(10, 10)

        header = Gtk.HBox()
        header.pack_start(self.image, False, False, 0)
        header.pack_start(self.title, False, False, 0)

        self.pack_start(header, False, True, 10)

        
    def get_title(self):
        pass

    def get_name(self):
        pass

    def get_icon_name(self):
        pass

    def get_primary_answer(self):
        pass

    def prepare(self):
        pass

    def seed(self, setup):
        pass

    def is_hidden(self):
        return False
