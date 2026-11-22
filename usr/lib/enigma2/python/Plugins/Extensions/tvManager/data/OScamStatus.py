#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
OSCam / NCam status screen for tvManager.

Same idea as the OpenATV OScamInfo (one table with server, readers and
clients, live log, memory bar), but standalone:
- works on any image (no BoxInfo, ServiceAction, setup.xml, image skin icons)
- finds the cam whoever started it (camwebif: version file or process)
- falls back to the XML api when JSON is not available
- network calls run in a thread, the GUI is only touched from the main thread
- start / stop / restart through the tvManager camscript
"""
from __future__ import print_function

import json
from os.path import exists

from enigma import (
    RT_HALIGN_CENTER, RT_HALIGN_LEFT, RT_VALIGN_CENTER, RT_WRAP,
    eListboxPythonMultiContent, eTimer, gFont, getDesktop)
from twisted.internet.reactor import callFromThread, callInThread

from Components.ActionMap import ActionMap
from Components.config import config
from Components.Console import Console
from Components.Label import Label
from Components.MenuList import MenuList
from Components.MultiContent import MultiContentEntryText
from Components.ScrollLabel import ScrollLabel
from Screens.ChoiceBox import ChoiceBox
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen
from xml.etree.ElementTree import XML

from . import _
from . import camwebif
from .camscripts import resolve_cam_id

try:
    from urllib.parse import unquote
except ImportError:
    from urllib import unquote

REFRESH_MS = 10000
SCALE = getDesktop(0).size().width() / 1920.0

# row background per client type (reader/proxy, client, server/http)
BG = {"p": 0xfcfce1, "r": 0xfcfce1, "c": 0xf1f6e6, "s": 0xe2e0ef, "h": 0xe2e0ef}
TYPE_ORDER = {"s": 0, "h": 1, "p": 2, "r": 3, "c": 4, "a": 5, "x": 6, "m": 7}
STATUS_COLOR = {"OK": 0x1b7a12, "CONNECTED": 0x1b7a12, "CARDOK": 0x1b7a12,
                "NEEDINIT": 0x9a7d00, "OFF": 0xc0261b, "ERROR": 0xc0261b,
                "UNKNOWN": 0x9a7d00}

# column (x, width) in 1920 coordinates, relative to the list
COLUMNS = [(0, 23), (25, 173), (200, 88), (290, 168), (460, 88), (550, 223),
           (775, 268), (1045, 233), (1280, 233), (1515, 163), (1680, 210)]
HEADERS = ["#", "Reader/User", "AU", "Address", "Port", "Protocol",
           "srvid:caid@provid", "Last Channel", "LB Value/Reader",
           "Online\nIdle", "Status"]


def s(v):
    return int(round(v * SCALE))


def current_cam():
    """Cam name written by tvManager (or by Black Hole images)."""
    for path in ("/etc/CurrentBhCamName", "/etc/clist.list"):
        try:
            with open(path) as f:
                name = f.read().strip().splitlines()[-1].strip()
            if name and name != "None":
                return resolve_cam_id(name)
        except (IOError, OSError, IndexError):
            continue
    return None


def fmt_seconds(value):
    try:
        sec = int(float(value))
    except (TypeError, ValueError):
        return "n/a"
    h, r = divmod(sec, 3600)
    m, sec = divmod(r, 60)
    return "%02d:%02d:%02d" % (h, m, sec)


def fmt_login(value):
    """'2026-11-19T12:32:13+0100' -> '12:32:13'."""
    if not value:
        return "n/a"
    if "T" in value:
        return value.split("T", 1)[1][:8]
    return value


def scroll_bottom(label):
    for name in ("lastPage", "moveBottom"):
        fn = getattr(label, name, None)
        if fn:
            try:
                fn()
            except Exception:
                pass
            return


class StatusList(MenuList):
    def __init__(self):
        MenuList.__init__(self, [], False, eListboxPythonMultiContent)
        self.l.setFont(0, gFont("Regular", s(26)))
        self.l.setFont(1, gFont("Regular", s(22)))
        self.l.setItemHeight(s(75))


def build_row(row):
    """row: dict with the 11 column values + 'type' + 'status_key'."""
    bg = BG.get(row["type"], 0xffffff)
    res = [row]
    values = [row["type"], row["user"], row["au"], row["ip"], row["port"],
              row["protocol"], row["srinfo"], row["channel"], row["lb"],
              row["times"], row["status"]]
    for idx, (x, w) in enumerate(COLUMNS):
        color = 0x000000
        if idx == 10:
            color = STATUS_COLOR.get(row.get("status_key", "").upper(), 0x000000)
        res.append(MultiContentEntryText(
            pos=(s(x), 0), size=(s(w), s(75)), font=0 if idx not in (6, 7, 8) else 1,
            flags=RT_HALIGN_CENTER | RT_VALIGN_CENTER | RT_WRAP,
            text=values[idx], color=color, color_sel=color,
            backcolor=bg, backcolor_sel=0xb0c4de))
    return res


class CamApi(object):
    """Thin wrapper around camwebif for one cam (oscam / ncam)."""

    def __init__(self, namebin):
        self.namebin = namebin
        self.settings = None
        self.url = ""

    def manual_settings(self):
        """Settings from the MENU > Setup screen when 'read from conf' is off."""
        try:
            if self.namebin == "ncam":
                from . import NcamInfo  # noqa: F401  (creates the config section)
                cfg = config.NcamInfo
            else:
                from . import OScamInfo  # noqa: F401
                cfg = config.tvm_oscaminfo
            if cfg.userdatafromconf.value:
                return None
            port = str(cfg.port.value)
            return {
                "proto": "https" if port.startswith("+") else "http",
                "host": ".".join("%d" % d for d in cfg.ip.value),
                "port": port.lstrip("+"),
                "user": str(cfg.username.value),
                "pwd": str(cfg.password.value),
                "conf": None,
            }
        except Exception as e:
            print("[OScamStatus] manual settings: %s" % e)
            return None

    def call(self, part="status", reader=None, fmt="json", extra=""):
        settings = self.manual_settings()
        if settings is None:
            settings, err = camwebif.get_webif_settings(self.namebin)
            if err:
                return False, err
        self.settings = settings
        self.url = "%s://%s:%s" % (settings["proto"], settings["host"], settings["port"])
        return camwebif.fetch(settings, self.namebin, part, reader, fmt, extra)

    # ---- status -------------------------------------------------------
    def status(self):
        ok, data = self.call("status", fmt="json")
        if ok:
            try:
                return True, self._parse_json(data)
            except Exception as e:
                print("[OScamStatus] JSON parse error, trying XML: %s" % e)
        ok, data = self.call("status", fmt="html")
        if not ok:
            return False, data
        try:
            return True, self._parse_xml(data)
        except Exception as e:
            return False, "invalid answer from webif: %s" % e

    def _parse_json(self, text):
        root = json.loads(text)
        js = root.get(self.namebin) or root.get("oscam") or root.get("ncam") or {}
        sysinfo = js.get("sysinfo", {})
        info = {
            "version": js.get("version", "n/a"),
            "srvidfile": js.get("srvidfile", ""),
            "starttime": js.get("starttime", ""),
            "runtime": js.get("runtime", ""),
            "mem": [
                ("Total", sysinfo.get("mem_cur_total")),
                ("Used", sysinfo.get("mem_cur_used")),
                ("Free", sysinfo.get("mem_cur_free")),
                ("Buffer", sysinfo.get("mem_cur_buff")),
                ("VM", sysinfo.get("%s_vmsize" % self.namebin)),
                ("RSS", sysinfo.get("%s_rsssize" % self.namebin)),
            ],
        }
        rows = []
        for c in js.get("status", {}).get("client", []):
            ctype = c.get("type", "")
            conn = c.get("connection", {}) or {}
            req = c.get("request", {}) or {}
            times = c.get("times", {}) or {}
            if ctype in ("s", "h"):
                user = "root"
            elif ctype in ("p", "r"):
                user = unquote(c.get("rname_enc", c.get("name", "")))
            else:
                user = unquote(c.get("name_enc", c.get("name", "")))
            status = conn.get("status", "n/a")
            status_key = status
            tot = str(conn.get("totentitlements", "0"))
            tot = int(tot) if tot.isdigit() else 0
            if ctype in ("p", "r"):
                if tot:
                    status += "\n(%s entitlements)" % tot
                else:
                    loc = mx = 0
                    for ent in conn.get("entitlements", []) or []:
                        for key, val in ent.items():
                            val = str(val)
                            if val.isdigit():
                                if key == "locals":
                                    loc = max(loc, int(val))
                                if key.startswith("ccc") or key == "locals":
                                    mx = max(mx, int(val))
                    status += "\n(%s of %s cards)" % (loc, mx)
            answered = req.get("answered", "")
            ecmtime = req.get("ecmtime", "")
            idle = times.get("idle")
            rows.append({
                "type": ctype,
                "user": user,
                "au": {"-1": "ON", "0": "OFF", "1": "ACTIVE"}.get(str(c.get("au", "")), "n/a"),
                "ip": conn.get("ip", ""),
                "port": str(conn.get("port", "")),
                "protocol": "\n".join(c.get("protocol", "").split(" ")),
                "srinfo": "%s:%s@%s" % (req.get("srvid", "n/a"), req.get("caid", "n/a"), req.get("provid", "n/a")),
                "channel": "%s\n%s" % (req.get("chname", ""), req.get("chprovider", "")) if req.get("chname") else "",
                "lb": "%s (%s ms)" % (answered, ecmtime) if answered and ecmtime else str(req.get("lbvalue", "")),
                "times": "%s\n%s" % (fmt_login(times.get("login")), fmt_seconds(idle) if idle not in (None, "") else "n/a"),
                "status": status,
                "status_key": status_key,
                "has_entitlements": ctype in ("p", "r"),
            })
        rows.sort(key=lambda r: TYPE_ORDER.get(r["type"], 9))
        return info, rows

    def _parse_xml(self, text):
        root = XML(text)
        info = {
            "version": root.get("version", "n/a"),
            "srvidfile": "",
            "starttime": root.get("starttime", ""),
            "runtime": fmt_seconds(root.get("uptime")) if root.get("uptime") else "",
            "mem": [],
        }
        rows = []
        status = root.find("status")
        for c in (status.findall("client") if status is not None else []):
            ctype = c.get("type", "")
            req = c.find("request")
            conn = c.find("connection")
            times = c.find("times")
            ra = req.attrib if req is not None else {}
            ca = conn.attrib if conn is not None else {}
            ta = times.attrib if times is not None else {}
            st = ((conn.text or "") if conn is not None else "").strip() or "n/a"
            channel = (req.text or "").strip() if req is not None else ""
            if ":" in channel:
                channel = channel.split(":", 1)[1].strip()
            ecmtime = ra.get("ecmtime", "")
            rows.append({
                "type": ctype,
                "user": "root" if ctype in ("s", "h") else c.get("name", ""),
                "au": {"-1": "ON", "0": "OFF", "1": "ACTIVE"}.get(c.get("au", ""), c.get("au", "")),
                "ip": "" if ca.get("ip") == "0.0.0.0" else ca.get("ip", ""),
                "port": ca.get("port", ""),
                "protocol": "\n".join(c.get("protocol", "").split(" ")),
                "srinfo": "%s:%s@%s" % (ra.get("srvid", "n/a"), ra.get("caid", "n/a"), ra.get("provid", "n/a")),
                "channel": channel,
                "lb": "%s ms" % ecmtime if ecmtime not in ("", "0") else "",
                "times": "%s\n%s" % (fmt_login(ta.get("login")), fmt_seconds(ta.get("idle")) if ta.get("idle") else "n/a"),
                "status": st,
                "status_key": st,
                "has_entitlements": ctype in ("p", "r"),
            })
        rows.sort(key=lambda r: TYPE_ORDER.get(r["type"], 9))
        return info, rows

    # ---- log ----------------------------------------------------------
    def log(self):
        ok, data = self.call("status", fmt="html", extra="&appendlog=1")
        if not ok:
            return False, data
        try:
            if "<![CDATA" not in data:
                data = data.replace("<log>", "<log><![CDATA[").replace("</log>", "]]></log>")
            node = XML(data).find("log")
            text = (node.text or "").strip() if node is not None else ""
            return True, text or _("<no log found>")
        except Exception as e:
            return False, "log parse error: %s" % e

    # ---- entitlements -------------------------------------------------
    def entitlements(self, reader):
        lines = []
        ok, data = self.call("entitlement", reader=reader, fmt="json")
        if ok:
            try:
                root = json.loads(data)
                js = root.get(self.namebin) or root.get("oscam") or {}
                for e in js.get("entitlements", []):
                    lines.append("%-6s %-5s %-7s %-10s %s -> %s  %s" % (
                        e.get("type", ""), e.get("caid", ""), e.get("provid", ""),
                        e.get("class", ""), str(e.get("startDate", ""))[:10],
                        str(e.get("expireDate", ""))[:10], e.get("name", "")))
            except Exception as e:
                print("[OScamStatus] entitlements json: %s" % e)
        if not lines:  # CCcam/proxy readers: XML card list
            ok, data = self.call("entitlement", reader=reader, fmt="html")
            if not ok:
                return False, data
            try:
                rdr = XML(data).find("reader")
                cl = rdr.find("cardlist") if rdr is not None else None
                for card in (cl.findall("card") if cl is not None else []):
                    provs = card.find("providers")
                    ptxt = ", ".join("%s %s" % (p.get("provid", ""), p.text or "")
                                     for p in (provs.findall("provider") if provs is not None else []))
                    lines.append("CAID %s  %s  hop %s  reshare %s  %s" % (
                        card.get("caid", ""), card.get("system", ""), card.get("hop", ""),
                        card.get("reshare", ""), ptxt))
            except Exception as e:
                return False, "entitlement parse error: %s" % e
        return True, "\n".join(lines) if lines else _("No entitlements for '%s'") % reader


class TextScreen(Screen):
    """Full screen scrollable text (log, capabilities, entitlements)."""

    def __init__(self, session, title, text_or_loader, refresh=False):
        self.skin = """
        <screen position="0,0" size="%d,%d" backgroundColor="#10101010" flags="wfNoBorder">
            <widget name="title" position="%d,%d" size="%d,%d" font="Regular;%d" halign="center" valign="center" foregroundColor="white" backgroundColor="#10101010"/>
            <widget name="text" position="%d,%d" size="%d,%d" font="Regular;%d" foregroundColor="black" backgroundColor="#ECEAF6"/>
        </screen>""" % (s(1920), s(1080), s(15), s(15), s(1890), s(60), s(40),
                        s(15), s(85), s(1890), s(980), s(24))
        Screen.__init__(self, session)
        self.loader = text_or_loader if callable(text_or_loader) else None
        self.closed = False
        self["title"] = Label(title)
        self["text"] = ScrollLabel("" if self.loader else text_or_loader)
        self["actions"] = ActionMap(["OkCancelActions", "DirectionActions"], {
            "ok": self.exit, "cancel": self.exit,
            "up": self["text"].pageUp, "down": self["text"].pageDown,
            "left": self["text"].pageUp, "right": self["text"].pageDown}, -1)
        self.timer = eTimer()
        try:
            self.timer_conn = self.timer.timeout.connect(self.load)
        except AttributeError:
            self.timer.callback.append(self.load)
        self.refresh = refresh
        if self.loader:
            self.onLayoutFinish.append(self.load)

    def load(self):
        def work():
            result = self.loader()
            callFromThread(self.show_text, result)
        callInThread(work)

    def show_text(self, result):
        if self.closed:
            return
        ok, text = result
        self["text"].setText(text if ok else _("Error") + ":\n" + text)
        if ok and self.refresh:
            scroll_bottom(self["text"])
            self.timer.start(REFRESH_MS, True)

    def exit(self):
        self.closed = True
        self.timer.stop()
        self.close()


class OSCamStatus(Screen):
    NAMEBIN = "oscam"
    CAMNAME = "OSCam"

    def __init__(self, session):
        self.skin = self.build_skin()
        Screen.__init__(self, session)
        self.api = CamApi(self.NAMEBIN)
        self.rows = []
        self.running = False
        self.closed = False
        self.busy = False
        self.console = Console()
        self.setTitle("%s Info" % self.CAMNAME)
        self["title"] = Label("%sInfo (tvManager)" % self.CAMNAME)
        self["buildinfos"] = Label("")
        self["extrainfos"] = Label(_("Connecting..."))
        self["timerinfos"] = Label("")
        for i, h in enumerate(HEADERS):
            self["h%d" % i] = Label(h)
        self["list"] = StatusList()
        self["logtext"] = ScrollLabel("")
        self["mem"] = Label("")
        self["key_red"] = Label("")
        self["key_green"] = Label("")
        self["key_yellow"] = Label(_("Capabilities"))
        self["key_blue"] = Label(_("Show Log"))
        self["key_info"] = Label(_("OK: Entitlements   MENU: more"))
        self["actions"] = ActionMap(
            ["OkCancelActions", "ColorActions", "MenuActions", "DirectionActions"], {
                "ok": self.key_ok,
                "cancel": self.exit,
                "red": self.key_stop,
                "green": self.key_start,
                "yellow": self.key_capabilities,
                "blue": self.key_log,
                "menu": self.key_menu,
                "up": self["list"].up,
                "down": self["list"].down,
                "left": self["list"].pageUp,
                "right": self["list"].pageDown,
            }, -1)
        self.timer = eTimer()
        try:
            self.timer_conn = self.timer.timeout.connect(self.refresh)
        except AttributeError:
            self.timer.callback.append(self.refresh)
        self.onLayoutFinish.append(self.refresh)
        self.onClose.append(self.cleanup)

    # ---- skin ---------------------------------------------------------
    def build_skin(self):
        W, LX, LY, LW, LH = s(1920), s(15), s(222), s(1890), s(600)
        parts = ['<screen position="0,0" size="%d,%d" backgroundColor="#10101010" flags="wfNoBorder">' % (W, s(1080))]
        lab = '<widget name="%s" position="%d,%d" size="%d,%d" font="Regular;%d" halign="%s" valign="center" foregroundColor="%s" backgroundColor="%s" transparent="%d"/>'
        parts.append(lab % ("title", s(15), s(10), s(1890), s(58), s(40), "center", "white", "#10101010", 1))
        parts.append('<widget source="global.CurrentTime" render="Label" position="%d,%d" size="%d,%d" font="Regular;%d" halign="right" valign="center" foregroundColor="white" backgroundColor="#10101010" transparent="1"><convert type="ClockToText">Format:%%H:%%M:%%S</convert></widget>' % (s(1600), s(10), s(300), s(58), s(40)))
        parts.append(lab % ("buildinfos", s(15), s(70), s(1890), s(38), s(28), "center", "#0092CBDF", "#10101010", 1))
        parts.append(lab % ("extrainfos", s(15), s(108), s(1890), s(34), s(26), "center", "#00FFD700", "#10101010", 1))
        parts.append(lab % ("timerinfos", s(15), s(142), s(1890), s(34), s(26), "center", "white", "#10101010", 1))
        for i, (x, w) in enumerate(COLUMNS):
            parts.append(lab % ("h%d" % i, LX + s(x), s(180), s(w), s(40), s(22), "center", "white", "#105a5a5a", 0))
        parts.append('<widget name="list" position="%d,%d" size="%d,%d" backgroundColor="#10b3b3b3" scrollbarMode="showOnDemand" enableWrapAround="1"/>' % (LX, LY, LW, LH))
        parts.append('<widget name="logtext" position="%d,%d" size="%d,%d" font="Regular;%d" foregroundColor="black" backgroundColor="#10ECEAF6"/>' % (LX, s(826), LW, s(140), s(22)))
        parts.append(lab % ("mem", LX, s(970), LW, s(40), s(26), "center", "white", "#105a5a5a", 0))
        for i, color in enumerate(("red", "green", "yellow", "blue")):
            x = s(20 + i * 300)
            parts.append('<eLabel position="%d,%d" size="%d,%d" backgroundColor="%s"/>' % (x, s(1020), s(8), s(45), color))
            parts.append(lab % ("key_%s" % color, x + s(18), s(1020), s(270), s(45), s(28), "left", "grey", "#10101010", 1))
        parts.append(lab % ("key_info", s(1230), s(1020), s(675), s(45), s(26), "right", "grey", "#10101010", 1))
        parts.append("</screen>")
        return "\n".join(parts)

    # ---- data ---------------------------------------------------------
    def refresh(self):
        if self.busy or self.closed:
            return
        self.busy = True

        def work():
            status = self.api.status()
            log = self.api.log() if status[0] else (False, "")
            callFromThread(self.apply, status, log)
        callInThread(work)

    def apply(self, status, log):
        self.busy = False
        if self.closed:
            return
        ok, payload = status
        self.running = ok
        if ok:
            info, rows = payload
            self.rows = rows
            self["buildinfos"].setText("%s: %s | %s | Host: %s" % (
                self.CAMNAME, info["version"],
                "srvidfile: %s" % info["srvidfile"] if info["srvidfile"] else "",
                self.api.url))
            self["extrainfos"].setText("")
            self["timerinfos"].setText("Start: %s | Run Time: %s" % (
                fmt_login(info["starttime"]) if info["starttime"] else "n/a",
                info["runtime"] or "n/a"))
            self["mem"].setText("   |   ".join("%s: %s" % (k, v) for k, v in info["mem"] if v))
            idx = self["list"].getSelectedIndex() if self.rows else 0
            self["list"].setList([build_row(r) for r in rows])
            if rows:
                self["list"].moveToIndex(min(idx, len(rows) - 1))
            if log[0]:
                self["logtext"].setText(log[1])
                scroll_bottom(self["logtext"])
        else:
            self.rows = []
            self["list"].setList([])
            self["buildinfos"].setText(self.api.url or "")
            msg = payload
            if current_cam():
                msg += "   -   " + _("GREEN: start %s") % current_cam()
            self["extrainfos"].setText(msg)
            self["timerinfos"].setText("")
            self["mem"].setText("")
            self["logtext"].setText("")
        self.update_keys()
        self.timer.start(REFRESH_MS, True)

    def update_keys(self):
        cam = current_cam()
        if self.running:
            self["key_red"].setText(_("Stop %s") % self.CAMNAME)
            self["key_green"].setText(_("Restart %s") % self.CAMNAME)
        else:
            self["key_red"].setText("")
            self["key_green"].setText(_("Start %s") % self.CAMNAME if cam else "")

    # ---- keys ---------------------------------------------------------
    def selected_row(self):
        cur = self["list"].getCurrent()
        if isinstance(cur, (list, tuple)):
            cur = cur[0] if cur else None
        return cur if isinstance(cur, dict) else None

    def key_ok(self):
        row = self.selected_row()
        if not row or not row.get("has_entitlements"):
            return
        reader = row["user"]
        self.session.open(TextScreen, _("Entitlements for '%s'") % reader,
                          lambda: self.api.entitlements(reader))

    def key_log(self):
        self.session.open(TextScreen, "%s Log" % self.CAMNAME, self.api.log, refresh=True)

    def key_capabilities(self):
        path = camwebif._version_file(self.NAMEBIN)
        text = _("<no capabilities found>")
        if path and exists(path):
            try:
                with open(path) as f:
                    text = f.read()
            except (IOError, OSError) as e:
                text = str(e)
        self.session.open(TextScreen, "%s Capabilities" % self.CAMNAME, text)

    def camscript(self, action):
        cam = current_cam()
        script = "/usr/camscript/%s.sh" % cam if cam else None
        if not script or not exists(script):
            self.session.open(MessageBox, _("No tvManager camscript for the current cam."),
                              MessageBox.TYPE_ERROR, timeout=5)
            return
        self["extrainfos"].setText(_("Please wait..."))
        self.timer.stop()
        self.console.ePopen("%s %s" % (script, action), self.camscript_done)

    def camscript_done(self, result, retval, extra_args=None):
        if self.closed:
            return
        if retval:
            self["extrainfos"].setText(_("camscript exit code %s") % retval)
        self.timer.start(3000, True)  # give the cam time to open the webif

    def key_start(self):
        if self.running:
            self.session.openWithCallback(
                lambda yes: yes and self.camscript("cam_res"), MessageBox,
                _("Restart %s?") % self.CAMNAME, MessageBox.TYPE_YESNO, default=False)
        elif current_cam():
            self.camscript("cam_up")

    def key_stop(self):
        if self.running:
            self.session.openWithCallback(
                lambda yes: yes and self.camscript("cam_down"), MessageBox,
                _("Stop %s?") % self.CAMNAME, MessageBox.TYPE_YESNO, default=False)

    def key_menu(self):
        choices = [
            (_("ECM info"), "ecm"),
            (_("Reader statistics"), "stats"),
            (_("Setup (manual IP / user)"), "setup"),
        ]
        self.session.openWithCallback(self.menu_done, ChoiceBox,
                                      title="%s Info" % self.CAMNAME, list=choices)

    def menu_done(self, choice):
        if not choice:
            return
        try:
            if self.NAMEBIN == "ncam":
                from . import NcamInfo as mod
                setup = mod.NcamInfoConfigScreen
            else:
                from . import OScamInfo as mod
                setup = mod.OscamInfoConfigScreen
            if choice[1] == "ecm":
                if exists("/tmp/ecm.info"):
                    self.session.open(mod.oscECMInfo)
                else:
                    self.session.open(MessageBox, _("No ECM info is currently available."),
                                      MessageBox.TYPE_INFO, timeout=5)
            elif choice[1] == "stats":
                self.session.open(mod.oscReaderStats, "all")
            elif choice[1] == "setup":
                self.session.open(setup)
        except Exception as e:
            self.session.open(MessageBox, str(e), MessageBox.TYPE_ERROR, timeout=8)

    def cleanup(self):
        self.closed = True
        self.timer.stop()

    def exit(self):
        self.close()


class NCamStatus(OSCamStatus):
    NAMEBIN = "ncam"
    CAMNAME = "NCam"
