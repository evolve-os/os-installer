#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
#  live_page.py - Screen shown when user bails out to livecd
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


class LivePage(Gtk.VBox):

    def __init__(self):
        Gtk.VBox.__init__(self)

        label = "<big>%s</big>\n\n%s" % (_("Thank you for using Solus Operating System."), _("Please use the button in the top right corner to close this window.\nYou may restart the installer at any time from the Budgie Menu"))
        label_wid = Gtk.Label(label)
        label_wid.set_use_markup(True)
        self.pack_start(label_wid, True, False, 0)

        # Add content
