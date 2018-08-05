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
from gi.repository import Gtk
from os_installer2.users import User, USERNAME_REGEX, PASSWORD_LENGTH
import re
import unicodedata

LABEL_COLUMN = 0
DATA_COLUMN = 1


class UserPanel(Gtk.Box):
    """Userpanel. Represents a user. Whoda thunk it. """

    def __init__(self, user):
        Gtk.Box.__init__(self, orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self.user = user

        label = Gtk.Label("<big>{}</big> - {}".format(
            self.user.realname,
            self.user.username))
        label.set_use_markup(True)
        label_details = Gtk.Label("")
        details = ""

        if self.user.autologin:
            details += "     - {}".format(
                "will be automatically logged into the computer")
        else:
            details += "     - {}".format(
                "will use a password to log into the computer")
        if self.user.admin:
            details += "\n     - {}".format(
                "will have administrative capabilities")
        else:
            details += "\n     - {}".format("will be an ordinary user")

        label_details.set_markup(details)
        label.set_halign(Gtk.Align.START)
        label_details.set_halign(Gtk.Align.START)
        self.pack_start(label, True, True, 4)
        self.pack_start(label_details, False, False, 0)


class NewUserPage(Gtk.Grid):
    """ Form for creating a new user """

    uname_field = None
    rname_field = None
    pword_field = None
    pword_field2 = None

    def is_bad_field(self, field):
        """ Validation for gecos """
        t = field.get_text()
        if len(t) < 2:
            return True
        bad_guys = ['"', '\'', '/', '\\', ';', '@', '!']
        hits = [x for x in bad_guys if x in t]
        if len(hits) > 0:
            return True
        return False

    def validator(self, entry):
        if entry == self.uname_field:
            # Perform username validation
            if self.username_regex.match(entry.get_text()):
                self.uname_field.set_icon_from_icon_name(
                    Gtk.EntryIconPosition.SECONDARY, "emblem-ok-symbolic")
                self.update_score(self.uname_field, True)
            else:
                # Username = bad
                self.uname_field.set_icon_from_icon_name(
                    Gtk.EntryIconPosition.SECONDARY,
                    "action-unavailable-symbolic")
                self.update_score(self.uname_field, False)
        elif entry == self.rname_field:
            if not self.is_bad_field(self.rname_field):
                self.rname_field.set_icon_from_icon_name(
                    Gtk.EntryIconPosition.SECONDARY, "emblem-ok-symbolic")
                self.update_score(self.rname_field, True)
            else:
                # Bad realname
                self.rname_field.set_icon_from_icon_name(
                    Gtk.EntryIconPosition.SECONDARY,
                    "action-unavailable-symbolic")
                self.update_score(self.rname_field, False)
        else:
            # Handle the two password fields together
            pass1 = self.pword_field.get_text()
            pass2 = self.pword_field2.get_text()

            if len(pass1) >= PASSWORD_LENGTH:
                self.pword_field.set_icon_from_icon_name(
                    Gtk.EntryIconPosition.SECONDARY, "emblem-ok-symbolic")
                self.update_score(self.pword_field, True)
            else:
                # Bad password
                self.pword_field.set_icon_from_icon_name(
                    Gtk.EntryIconPosition.SECONDARY,
                    "action-unavailable-symbolic")
                self.update_score(self.pword_field, False)

            if len(pass1) >= PASSWORD_LENGTH and pass1 == pass2:
                self.pword_field2.set_icon_from_icon_name(
                    Gtk.EntryIconPosition.SECONDARY, "emblem-ok-symbolic")
                self.update_score(self.pword_field2, True)
            else:
                # Bad password2
                self.pword_field2.set_icon_from_icon_name(
                    Gtk.EntryIconPosition.SECONDARY,
                    "action-unavailable-symbolic")
                self.update_score(self.pword_field2, False)

    def suggest_username(self, widget):
        """Suggest an username based on the real name"""
        # Convert realname to unicode
        uname = unicode(self.rname_field.get_text(), "utf-8")
        # Turn into lowercase
        uname = uname.lower()
        # Replace non-ASCII characters (i.e. á -> a)
        uname = unicodedata.normalize("NFKD", uname)
        # Remove non-alphanumeric symbols and spaces
        uname = re.sub("[^-a-z0-9_]", "", uname)

        self.uname_field.set_text(uname)

    def update_score(self, widget, score):
        """ Update the score for validation """
        if widget not in self.scores:
            self.scores[widget] = score
        else:
            self.scores[widget] = score

        total_score = len([i for i in self.scores.values() if i])
        self.ok.set_sensitive(total_score == self.needed_score)

    def __init__(self, owner):
        Gtk.Grid.__init__(self)
        self.owner = owner
        self.set_margin_top(40)

        self.set_column_spacing(10)
        self.set_row_spacing(10)
        self.set_margin_left(100)
        self.set_margin_right(100)

        self.scores = dict()
        self.needed_score = 4

        self.username_regex = re.compile(USERNAME_REGEX)

        row = 0
        rname_label = Gtk.Label("Real name:")
        self.rname_field = Gtk.Entry()
        self.rname_field.connect("changed", self.validator)
        self.rname_field.connect("changed", self.suggest_username)
        self.attach(rname_label, LABEL_COLUMN, row, 1, 1)
        self.attach(self.rname_field, DATA_COLUMN, row, 1, 1)

        row += 1
        uname_label = Gtk.Label("Username:")
        self.uname_field = Gtk.Entry()
        self.uname_field.set_hexpand(True)
        self.uname_field.connect("changed", self.validator)
        self.attach(uname_label, LABEL_COLUMN, row, 1, 1)
        self.attach(self.uname_field, DATA_COLUMN, row, 1, 1)

        row += 1
        pword_label = Gtk.Label("Password:")
        self.pword_field = Gtk.Entry()
        self.pword_field.set_visibility(False)
        self.pword_field.connect("changed", self.validator)
        self.attach(pword_label, LABEL_COLUMN, row, 1, 1)
        self.attach(self.pword_field, DATA_COLUMN, row, 1, 1)

        row += 1
        pword_label2 = Gtk.Label("Confirm password:")
        self.pword_field2 = Gtk.Entry()
        self.pword_field2.connect("changed", self.validator)
        self.pword_field2.set_visibility(False)
        self.attach(pword_label2, LABEL_COLUMN, row, 1, 1)
        self.attach(self.pword_field2, DATA_COLUMN, row, 1, 1)

        row += 1
        # And now an administrative user check
        self.adminuser = Gtk.CheckButton(
            "This user should have administrative capabilities")
        self.attach(self.adminuser, DATA_COLUMN, row, 1, 1)

        row += 1
        btnbox = Gtk.ButtonBox()
        btnbox.set_spacing(5)
        # Lastly the action buttons
        self.ok = Gtk.Button("Add now")
        self.ok.get_style_context().add_class("suggested-action")
        ok_image = Gtk.Image()
        ok_image.set_from_icon_name("list-add-symbolic", Gtk.IconSize.BUTTON)
        self.ok.set_image(ok_image)
        self.ok.set_sensitive(False)
        self.ok.connect("clicked", self.add_user)

        self.cancel = Gtk.Button("Cancel")
        self.cancel.connect("clicked", lambda x: self.owner.show_main())
        cancel_image = Gtk.Image()
        cancel_image.set_from_icon_name("window-close-symbolic",
                                        Gtk.IconSize.BUTTON)
        self.cancel.set_image(cancel_image)

        btnbox.set_layout(Gtk.ButtonBoxStyle.START)
        btnbox.set_margin_top(10)
        btnbox.add(self.ok)
        btnbox.add(self.cancel)
        self.attach(btnbox, DATA_COLUMN, row, 1, 1)

        for label in [uname_label, rname_label, pword_label, pword_label2]:
            label.set_halign(Gtk.Align.START)

    def clear_form(self):
        """ Clear the form state """
        items = [
            self.uname_field,
            self.rname_field,
            self.pword_field,
            self.pword_field2
        ]
        for entry in items:
            entry.set_text("")
            entry.set_icon_from_icon_name(
                Gtk.EntryIconPosition.SECONDARY, None)
        for check in [self.adminuser]:
            check.set_active(False)
        self.adminuser.set_sensitive(True)

    def add_user(self, w=None):
        user = User(self.uname_field.get_text(),
                    self.rname_field.get_text(),
                    self.pword_field.get_text(),
                    False,
                    self.adminuser.get_active())
        self.owner.add_new_user(user)
        self.owner.show_main()


class InstallerUsersPage(BasePage):
    """ User management. """

    info = None
    had_init = False

    def __init__(self):
        BasePage.__init__(self)

        self.listbox = Gtk.ListBox()
        self.listbox.connect("row-activated", self.activated)
        scroller = Gtk.ScrolledWindow(None, None)
        scroller.add(self.listbox)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_shadow_type(Gtk.ShadowType.ETCHED_IN)
        scroller.get_style_context().set_junction_sides(
            Gtk.JunctionSides.BOTTOM)

        # Placeholder stuff
        placeholder = Gtk.Label("<big>{}</big>".format(
            "You haven\'t added any users yet."))
        placeholder.set_use_markup(True)
        placeholder.show()
        self.listbox.set_placeholder(placeholder)

        toolbar = Gtk.Toolbar()
        toolbar.set_icon_size(Gtk.IconSize.SMALL_TOOLBAR)
        toolbar.get_style_context().add_class(Gtk.STYLE_CLASS_INLINE_TOOLBAR)
        junctions = Gtk.JunctionSides.TOP
        toolbar.get_style_context().set_junction_sides(junctions)

        add = Gtk.ToolButton()
        add.connect("clicked", self.add_user)
        add.set_icon_name("list-add-symbolic")
        toolbar.add(add)

        self.remove = Gtk.ToolButton()
        self.remove.set_icon_name("list-remove-symbolic")
        self.remove.set_sensitive(False)
        self.remove.connect("clicked", self.delete_user)
        toolbar.add(self.remove)

        # We use a stack here too, because dialogs are horrible.
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_UP_DOWN)
        self.pack_start(self.stack, True, True, 0)

        main_page = Gtk.Box.new(Gtk.Orientation.VERTICAL, 0)
        main_page.pack_start(scroller, True, True, 0)
        main_page.pack_start(toolbar, False, False, 0)
        main_page.set_border_width(40)

        self.stack.add_named(main_page, "main")

        self.add_user_page = NewUserPage(self)
        self.stack.add_named(self.add_user_page, "add-user")

    def activated(self, box, row):
        if row is None:
            self.remove.set_sensitive(False)
            return
        self.remove.set_sensitive(True)

    def delete_user(self, w=None):
        row = self.listbox.get_selected_row()
        if row is None:
            self.remove.set_sensitive(False)
            return
        user = row.get_children()[0].user
        self.info.users.remove(user)
        self.listbox.remove(row)
        self.remove.set_sensitive(False)

        if len(self.info.users) == 0:
            self.info.owner.set_can_next(False)

    def add_user(self, widget):
        admins = [user for user in self.info.users if user.admin]
        self.stack.set_visible_child_name("add-user")
        if len(admins) == 0:
            # Force this new user to be an administrator
            self.add_user_page.adminuser.set_sensitive(False)
            self.add_user_page.adminuser.set_active(True)
        self.info.owner.set_can_previous(False)

    def add_new_user(self, user):
        self.info.users.append(user)
        user_panel = UserPanel(user)
        self.listbox.add(user_panel)
        self.listbox.show_all()
        self.info.owner.set_can_next(True)

    def show_main(self):
        self.stack.set_visible_child_name("main")
        self.info.owner.set_can_previous(True)
        self.add_user_page.clear_form()

    def prepare(self, info):
        self.info = info
        if not self.info.users:
            self.info.users = list()

        self.info.owner.set_can_previous(True)
        self.info.owner.set_can_next(len(self.info.users) > 0)
        self.stack.set_visible_child_name("main")
        self.show_all()
        self.add_user_page.clear_form()

        # Start on the new user page
        if not self.had_init:
            self.add_user(None)
            self.had_init = True

    def get_title(self):
        return "Who will use this device?"

    def get_sidebar_title(self):
        return "Users"

    def get_name(self):
        return "users"

    def get_icon_name(self, plasma=False):
        return "system-users"
