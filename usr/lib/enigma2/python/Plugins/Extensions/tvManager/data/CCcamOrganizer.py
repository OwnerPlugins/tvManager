#!/usr/bin/env python
# -*- coding: UTF-8 -*-

# CCcam Organizer by fsenes 2011
# modded by lululla 20240314 - tvManager fixes:
# - works on the CCcam.cfg found by CCcamInfo (not only /etc/CCcam.cfg)
# - no global state between screens
# - only the "C:" prefix of a line is changed (never text inside passwords)
# - "C :" lines are handled too
from Screens.Screen import Screen
from Components.MenuList import MenuList
from Components.ActionMap import ActionMap
from Screens.MessageBox import MessageBox
from Tools.Directories import fileExists
from . import _

DEFAULT_CFG = "/etc/CCcam.cfg"
ACTIVE = ("C:", "C :")
DELETED = ("#!C:", "#!C :")
FAKE = ("#FC:", "#FC :")


def _read(cfg):
    with open(cfg, "r") as f:
        return f.readlines()


def _write(cfg, lines):
    with open(cfg, "w") as f:
        f.writelines(lines)


def _swap_prefix(line, old_prefixes, new_prefix):
    for old in old_prefixes:
        if line.startswith(old):
            return new_prefix + line[len(old):]
    return line


def _host(line):
    parts = line.replace("C :", "C:", 1).split()
    return parts[1] if len(parts) > 1 else line.strip()


class OrganizerMenu(Screen):
    skin = """
        <screen position="center,center" size="460,400" title="CCcam Organizer" >
            <widget name="myMenu" position="10,10" size="420,380" itemHeight="45" scrollbarMode="showOnDemand" />
        </screen>"""

    def __init__(self, session, cfg=DEFAULT_CFG):
        Screen.__init__(self, session)
        self.cfg = cfg or DEFAULT_CFG
        listx = []
        if fileExists(self.cfg):
            listx.append((_("Delete Peer"), "delete"))
            listx.append((_("Recover Peer"), "recover"))
            listx.append((_("Find Fakes"), "fakes"))
            listx.append((_("Stop Finding Fakes"), "revert"))
        listx.append((_("Exit"), "exit"))
        self.setTitle(_("CCcam Organizer") + " - " + self.cfg)
        self["myMenu"] = MenuList(listx)
        self["myActionMap"] = ActionMap(
            ["SetupActions"], {"ok": self.go, "cancel": self.cancel}, -2)

    def go(self):
        sel = self["myMenu"].l.getCurrentSelection()
        mode = sel and sel[1]
        if mode == "exit" or not fileExists(self.cfg):
            self.close(None)
        elif mode == "revert":
            self.revert()
        elif mode:
            self.session.open(OrganizerNewmenu, self.cfg, mode)

    def cancel(self):
        self.close(None)

    def revert(self):
        try:
            _write(self.cfg, [_swap_prefix(x, FAKE, "C:") for x in _read(self.cfg)])
            self.session.open(MessageBox, _("\nSTOPPED FINDING FAKES \n\nREVERTED BACK TO INITIAL STATUS"),
                              MessageBox.TYPE_INFO)
        except (IOError, OSError) as e:
            self.session.open(MessageBox, _("Failed to revert file: %s") % str(e), MessageBox.TYPE_ERROR)


class OrganizerNewmenu(Screen):
    skin = """
        <screen position="center,center" size="460,400" title="CCcam Organizer" >
            <widget name="Newmenu" position="10,10" size="420,380" scrollbarMode="showOnDemand" />
        </screen>"""

    def __init__(self, session, cfg, mode):
        Screen.__init__(self, session)
        self.cfg = cfg
        self.mode = mode
        prefixes = DELETED if mode == "recover" else ACTIVE
        menu_list = []
        try:
            for line in _read(cfg):
                if line.startswith(prefixes):
                    menu_list.append((_host(line), line))
        except (IOError, OSError) as e:
            print("[CCcamOrganizer] %s" % e)
        if not menu_list:
            menu_list.append((_("Nothing to show"), None))
        self.setTitle(_("CCcam Organizer"))
        self["Newmenu"] = MenuList(menu_list)
        action = {"delete": self.delete, "recover": self.undelete, "fakes": self.find_fakes}[mode]
        self["Actions"] = ActionMap(["SetupActions"], {"ok": action, "cancel": self.close}, -2)

    def selected(self):
        sel = self["Newmenu"].l.getCurrentSelection()
        return sel[1] if sel else None

    def _edit(self, func, done_text):
        line = self.selected()
        if not line:
            return
        try:
            _write(self.cfg, [func(x, line) for x in _read(self.cfg)])
            self.session.open(MessageBox, "\n%s \n\n%s" % (_host(line), done_text), MessageBox.TYPE_INFO)
        except (IOError, OSError) as e:
            self.session.open(MessageBox, _("Error while editing configuration: %s") % str(e),
                              MessageBox.TYPE_ERROR)

    def delete(self):
        self._edit(lambda x, sel: _swap_prefix(x, ACTIVE, "#!C:") if x == sel else x,
                   _("Temporarily DELETED"))

    def undelete(self):
        self._edit(lambda x, sel: _swap_prefix(x, DELETED, "C:") if x == sel else x,
                   _("UNDELETED"))

    def find_fakes(self):
        self._edit(lambda x, sel: x if x == sel else _swap_prefix(x, ACTIVE, "#FC:"),
                   _("Set as UNIQUE PEER"))
