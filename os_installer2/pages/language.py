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
from . import default_locales
from gi.repository import Gtk, GnomeDesktop, Gdk


class LcLabel(Gtk.Label):
    """ View label for locales, save code duping """

    lc_code = None
    untransl = None

    def __init__(self, lc_code):
        Gtk.Label.__init__(self)
        self.set_text(lc_code)
        self.set_halign(Gtk.Align.START)
        self.lc_code = lc_code

        # transl = GnomeDesktop.get_language_from_locale(lc_code, lc_code)
        untransl = GnomeDesktop.get_language_from_locale(lc_code, None)
        self.set_property("margin", 8)

        self.dname = untransl

        self.set_text(untransl)

        self.show()


class InstallerLanguagePage(BasePage):
    """ Basic language page. """

    # Scrollbox
    scroll = None

    # Main content
    listbox = None

    # SearchEntry
    searchbox = None

    info = None

    def __init__(self):
        BasePage.__init__(self)


        self.searchbox = Gtk.SearchEntry()
        self.searchbox.set_width_chars(30)
        self.searchbox.set_halign(Gtk.Align.CENTER)
        self.searchbox.set_margin_top(20)
        self.searchbox.connect("search-changed", self.search_filter)
        self.add(self.searchbox)

        self.scroll = Gtk.ScrolledWindow(None, None)
        self.scroll.set_shadow_type(Gtk.ShadowType.ETCHED_IN)
        self.scroll.set_border_width(20)
        self.add(self.scroll)

        self.listbox = Gtk.ListBox()
        self.scroll.add(self.listbox)
        self.scroll.set_halign(Gtk.Align.CENTER)

        self.scroll.set_size_request(500, 400)

        self.scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.listbox.connect_after("row-selected", self.on_row_select)

    def on_row_select(self, lbox, newrb=None):
        """ Handle selections of locales """
        self.info.locale = None
        self.info.locale_sz = None
        if not newrb:
            self.info.owner.set_can_next(False)
            return
        child = newrb.get_child()
        self.info.locale = child.lc_code
        self.info.locale_sz = child.dname
        self.info.owner.set_can_next(True)

    def do_expensive_init(self):
        """ Do the hard work of actually setting up the view """
        Gdk.threads_enter()
        all_locales = GnomeDesktop.get_all_locales()
        all_locales.sort()
        for lc in all_locales:
            self.listbox.add(LcLabel(lc))
        Gdk.threads_leave()


    def search_filter(self, entry):
        """ Provide the search results """
        for row in self.listbox:
            row.destroy()
        entry_str = entry.get_text().lower()
        all_locales = GnomeDesktop.get_all_locales()
        all_locales.sort()
        for lc in all_locales:
             if entry_str == "":
                self.listbox.add(LcLabel(lc))
             else:
                 if LcLabel(lc).get_text().lower().startswith(entry_str):
                    self.listbox.add(LcLabel(lc))
    
    def init_remaining(self):
        """ Add the rest to the list """

    def prepare(self, info):
        # Nothing to seed with.
        self.info = info
        if self.info.locale:
            self.info.owner.set_can_next(True)
        else:
            self.info.owner.set_can_next(False)

    def get_title(self):
        return "Choose a language"

    def get_sidebar_title(self):
        return "Language"

    def get_name(self):
        return "language"

    def get_icon_name(self):
        return "preferences-desktop-locale"
