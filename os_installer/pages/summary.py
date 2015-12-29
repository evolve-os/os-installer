#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
#  summary.py - Installation options summary
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

class SummaryItem(Gtk.VBox):

    def __init__(self, page):
        Gtk.VBox.__init__(self)

        frame = Gtk.Frame()
        container = Gtk.HBox()
        frame.set_shadow_type(Gtk.ShadowType.NONE)

        # title
        self.title = Gtk.Label("<big>%s</big>" % page.get_title())
        self.title.set_use_markup(True)
        self.title.set_alignment(0.1, 0.5)
        container.pack_start(self.title, False, False, 3)

        # primary answer
        self.primary = Gtk.Label("%s" % page.get_primary_answer())
        container.pack_end(self.primary, False, False, 0)

        container.set_border_width(10)
        frame.add(container)
        self.pack_start(frame, False, False, 0)


class SummaryPage(BasePage):

    def __init__(self, installer):
        BasePage.__init__(self)

        self.installer = installer

        self.store = Gtk.VBox()
        scroller = Gtk.ScrolledWindow(None,None)
        scroller.add(self.store)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        self.pack_start(scroller, True, True, 0)

    def _clear_widgets(self):
        for i in self.store.get_children():
            self.store.remove(i)

    def prepare(self, pages=None):
        self.installer.can_go_back(True)
        self.installer.can_go_forward(True) # Consider another button maybe.

        self._clear_widgets()
        for page in pages:
            summ = SummaryItem(page)
            self.store.pack_start(summ, False, False, 10)
        self.show_all()

    def get_title(self):
        return _("Summary")

    def get_name(self):
        return "summary"

    def get_icon_name(self):
        return "emblem-ok-symbolic"
