#!/usr/bin/env python
# -*- coding: UTF-8 -*-

from __future__ import print_function
import codecs
import json
import subprocess
import sys
import time
from base64 import b64decode
from datetime import datetime
from os import (
    makedirs,
    mkdir,
    access,
    X_OK,
    system,
    popen,
    chmod,
    remove,
    walk,
    listdir
)
from os.path import dirname, join, exists, islink, getmtime
from re import sub
from time import sleep
from xml.dom import minidom

from twisted.internet.reactor import callFromThread, callInThread

from Components.ActionMap import ActionMap, NumberActionMap
from Components.Button import Button
from Components.Label import Label
from Components.MenuList import MenuList
from Components.MultiContent import MultiContentEntryText
from Components.Sources.List import List
from Plugins.Plugin import PluginDescriptor
from Screens.MessageBox import MessageBox
from Screens.ChoiceBox import ChoiceBox
from Screens.Screen import Screen
from Screens.Standby import TryQuitMainloop
from Tools.Directories import resolveFilename, SCOPE_PLUGINS
from Tools.LoadPixmap import LoadPixmap
from enigma import (
    RT_HALIGN_LEFT,
    RT_VALIGN_CENTER,
    eListboxPythonMultiContent,
    eTimer,
    gFont,
    getDesktop,
)

from . import (
    _,
    __version__,
    # headers,
    paypal,
    installer_url,
    developer_url,
    ftpxml,
    NAME_PLUG,
    TITLE_PLUG,
    PLUGIN_PATH,
    ICONPIC,
    DATA_PATH,
    # DIR_WORK,
    # EMPTY_ECM_INFO
    FILE_XML,
    ECM_INFO
)


from .data.Utils import RequestAgent, b64decoder
from .data.GetEcmInfo import GetEcmInfo
from .data.Console import Console
from .data.camscripts import camscripts, resolve_cam_id, label_for

###############################################################################
#                                                                             #
#                      S O F T C A M   M A N A G E R                          #
#                                                                             #
#                     Enterprise Grade Enigma2 Plugin                         #
#                                                                             #
#     Copyright (c) 2024-2026 Lululla. All rights reserved.                   #
#     Skin Design by MMark. Licensed under GNU General Public License v3.0    #
#                                                                             #
#     Version: 3.7 Professional Edition      Build Date: 2026-11-22           #
#     Core Developer: Lululla                   Lead Designer: MMark          #
#     Architecture: Multi-Platform Enigma2      Python: 2.7/3.x Compatible    #
#                                                                             #
#     Official Repository: https://github.com/Belfagor2005/tvManager          #
#                                                                             #
#     This program is free software: you can redistribute it and/or modify    #
#     it under the terms of the GNU General Public License as published by    #
#     the Free Software Foundation, either version 3 of the License, or       #
#     (at your option) any later version.                                     #
#                                                                             #
#     This program is distributed in the hope that it will be useful,         #
#     but WITHOUT ANY WARRANTY; without even the implied warranty of          #
#     MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the            #
#     GNU General Public License for more details.                            #
#                                                                             #
#     For commercial licensing inquiries, contact: business@lululla.com       #
#                                                                             #
###############################################################################

global active, skin_path
global _session


active = False
_session = None
local = False
PY3 = sys.version_info.major >= 3

if PY3:
    unicode = str
    unichr = chr
    long = int
    PY3 = True
    from urllib.request import urlopen, Request
else:
    from urllib2 import urlopen, Request


old_ecm_time = time.time()
info = {}
ecm = ""
SOFTCAM = 0
CCCAMINFO = 1
OSCAMINFO = 2

AgentRequest = RequestAgent()


# =========================
# Utility Functions
# =========================
try:
    from shlex import quote as shell_quote
except ImportError:  # Python 2
    from pipes import quote as shell_quote


def http_get(url, timeout=15):
    """Download url (certificate checked). Returns (True, text) or (False, error)."""
    try:
        req = Request(
            url,
            headers={
                "User-Agent": AgentRequest,
                "Accept-Encoding": "identity"})
        resp = urlopen(req, timeout=timeout)
        data = resp.read()
        resp.close()
        if not isinstance(data, str):
            data = data.decode("utf-8", "ignore")
        return True, data
    except Exception as e:
        return False, str(e)


def fetch_async(url, on_ok, on_error, timeout=15):
    """http_get in a thread, callbacks on the GUI thread."""
    def work():
        ok, data = http_get(url, timeout)
        callFromThread(on_ok if ok else on_error, data)
    callInThread(work)


def version_tuple(v):
    out = []
    for part in str(v).replace("-", ".").split("."):
        num = "".join(c for c in part if c.isdigit())
        out.append(int(num) if num else 0)
    return tuple(out)


UPDATE_STAMP = "/etc/tvManager/last_update_check"
UPDATE_INTERVAL = 24 * 3600   # home screen checks GitHub at most once a day


def parse_installer(data):
    """(version, changelog) from the version=/changelog= lines of installer.sh."""
    version, changelog = "0.0", ""
    for line in data.split("\n"):
        if line.startswith("version") and "'" in line:
            version = line.split("'")[1]
        elif line.startswith("changelog") and "'" in line:
            changelog = line.split("'")[1].replace("\\n", "\n").strip()
            break
    return version, changelog


def update_check_due():
    try:
        return time.time() - getmtime(UPDATE_STAMP) >= UPDATE_INTERVAL
    except OSError:
        return True


def mark_update_checked():
    try:
        if not exists(dirname(UPDATE_STAMP)):
            makedirs(dirname(UPDATE_STAMP))
        with open(UPDATE_STAMP, "w") as f:
            f.write(str(int(time.time())))
    except (IOError, OSError) as e:
        print("[tvManager] update stamp: %s" % e)


def plugin_update_cmd():
    """Download installer.sh (TLS verified), then run it with /bin/sh."""
    return (
        "wget -q -O /tmp/tvmanager_installer.sh %s && /bin/sh /tmp/tvmanager_installer.sh; "
        "rc=$?; rm -f /tmp/tvmanager_installer.sh; exit $rc" %
        shell_quote(
            b64decoder(installer_url)))


def execute_cam_command(cmd):
    """Executes cam commands without blocking - uses simple system()"""
    print("Executing cam command: %s" % cmd)
    try:
        system(cmd)
        # Do not wait for completion, return immediately
        return True
    except Exception as e:
        print("Cam command error: %s" % str(e))
        return False


def safe_system_call(cmd, max_retries=3, timeout=30, background=False):
    """Execute system commands with intelligent management"""
    # Identify command type
    is_cam_command = "camscript" in cmd and (
        "cam_up" in cmd or "cam_down" in cmd or "cam_res" in cmd)
    is_background_command = background or cmd.strip().endswith('&')

    # For cam and background commands: use system() without waiting
    if is_cam_command or is_background_command:
        print("Executing background command: %s" % cmd)
        try:
            system(cmd)
            return True, "background_command_executed"
        except Exception as e:
            print("Background command error: %s" % str(e))
            return False, str(e)

    for attempt in range(max_retries):
        try:
            if PY3:
                result = subprocess.run(
                    cmd, shell=True, capture_output=True, timeout=timeout)
                if result.returncode == 0:
                    return True, result.stdout
                print("Attempt %d failed: %s" % (attempt + 1, result.stderr))
            else:
                import subprocess as sub
                result = sub.Popen(
                    cmd, shell=True, stdout=sub.PIPE, stderr=sub.PIPE)
                stdout, stderr = result.communicate()
                if result.returncode == 0:
                    return True, stdout
                print("Attempt %d failed: %s" % (attempt + 1, stderr))
        except subprocess.TimeoutExpired:
            print("Command timed out after %d seconds: %s" % (timeout, cmd))
            if attempt == max_retries - 1:
                return False, "timeout"
        except Exception as e:
            print("System call error: %s" % str(e))

        if attempt < max_retries - 1:
            sleep(2)

    return False, None


def execute_background_command(cmd):
    """For non-blocking commands (cam, backup, cleanup)"""
    print("Executing background: %s" % cmd)
    try:
        system(cmd)
        return True
    except Exception as e:
        print("Background command error: %s" % str(e))
        return False


def execute_blocking_command(cmd, max_retries=3, timeout=30):
    """For commands that need output (resource monitoring, checks)"""
    for attempt in range(max_retries):
        try:
            if PY3:
                result = subprocess.run(
                    cmd, shell=True, capture_output=True, timeout=timeout)
                if result.returncode == 0:
                    return True, result.stdout
                print("Attempt %d failed: %s" % (attempt + 1, result.stderr))
            else:
                import subprocess as sub
                result = sub.Popen(
                    cmd, shell=True, stdout=sub.PIPE, stderr=sub.PIPE)
                stdout, stderr = result.communicate()
                if result.returncode == 0:
                    return True, stdout
                print("Attempt %d failed: %s" % (attempt + 1, stderr))
        except Exception as e:
            print("Blocking command error: %s" % str(e))

        if attempt < max_retries - 1:
            sleep(2)

    return False, None


def get_resource_info_safe():
    """Get resource info without blocking - use alternative methods"""
    try:
        # For memory: read /proc/meminfo
        mem_info = ""
        if exists("/proc/meminfo"):
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    if "MemTotal" in line or "MemAvailable" in line:
                        mem_info += line.strip() + "\n"

        # For CPU: read /proc/loadavg
        cpu_info = ""
        if exists("/proc/loadavg"):
            with open("/proc/loadavg", "r") as f:
                cpu_info = f.read().strip()

        return mem_info, cpu_info

    except Exception as e:
        print("Safe resource info error: %s" % str(e))
        return "N/A", "N/A"


BACKUP_ROOT = "/etc/tvManager/backup"   # survives reboots (/tmp does not)
BACKUP_KEEP = 10


def backup_candidates():
    """Config files worth saving, including the running cam's config dir."""
    files = [
        "/etc/CCcam.cfg",
        "/etc/tuxbox/config/oscam.server",
        "/etc/tuxbox/config/oscam.conf",
        "/etc/tuxbox/config/oscam.user",
        "/etc/tuxbox/config/oscam.dvbapi",
        "/etc/tuxbox/config/ncam.server",
        "/etc/tuxbox/config/ncam.conf",
        "/etc/tuxbox/config/ncam.user",
        "/usr/keys/SoftCam.Key",
        "/etc/clist.list",
    ]
    try:
        from .data import camwebif
        for cam in ("oscam", "ncam"):
            confdir = camwebif.read_version_info(cam).get("confdir")
            if confdir:
                for name in ("server", "conf", "user", "dvbapi", "services"):
                    files.append(join(confdir, "%s.%s" % (cam, name)))
    except Exception as e:
        print("backup_candidates: %s" % e)
    seen, out = set(), []
    for f in files:
        if f not in seen and exists(f):
            seen.add(f)
            out.append(f)
    return out


def backup_configs(backup_name=None):
    """Copy the config files into BACKUP_ROOT/backup_<date>/<full path>."""
    import shutil
    if backup_name is None:
        backup_name = "backup_%s" % datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = join(BACKUP_ROOT, backup_name)
    backed_up = []
    try:
        for src in backup_candidates():
            dest = backup_dir + src
            if not exists(dirname(dest)):
                makedirs(dirname(dest))
            shutil.copy2(src, dest)
            backed_up.append(src)
        # keep only the newest BACKUP_KEEP backups
        old = sorted(d for d in listdir(BACKUP_ROOT)
                     if d.startswith("backup_"))
        for d in old[:-BACKUP_KEEP]:
            shutil.rmtree(join(BACKUP_ROOT, d), ignore_errors=True)
        print(
            "Backup completed: %d files saved in %s" %
            (len(backed_up), backup_dir))
        return backup_dir, backed_up
    except Exception as e:
        print("Error during backup: %s" % str(e))
        return None, []


def cleanup_temp_files():
    """Clean temporary files"""
    temp_patterns = [
        "/tmp/*.ipk",
        "/tmp/*.deb",
        "/tmp/*.tar.gz",
        "/tmp/*.zip",
        "/tmp/ecm.info.old"
    ]

    for pattern in temp_patterns:
        safe_system_call("rm -f %s" % pattern)


def check_dependencies():
    """Missing libraries (file check only: fast, no shell, no network)."""
    from glob import glob
    missing_deps = []
    libdirs = [
        "/usr/lib",
        "/lib",
        "/usr/lib32",
        "/usr/lib64",
        "/usr/lib/*",
        "/lib/*"]
    if not any(glob(join(d, "libusb-1.0.so*")) for d in libdirs):
        missing_deps.append("libusb-1.0-0")
    if not any(glob(join(d, "libssl.so*")) for d in libdirs):
        missing_deps.append("libssl")
    return missing_deps


def install_package():
    """Install necessary packages with error handling"""
    try:
        if exists("/usr/bin/apt-get"):  # DreamOS
            check_cmd = ["dpkg", "-l"]
            install_cmd = ["apt-get", "install", "-y"]
        else:  # OpenPLi/OpenATV
            check_cmd = ["opkg", "list-installed"]
            install_cmd = ["opkg", "install"]

        # Update repositories
        print("Updating package repositories...")
        if exists("/usr/bin/apt-get"):
            safe_system_call("apt-get update")
        else:
            safe_system_call("opkg update")

        # Install libusb if necessary
        libusb_check = safe_system_call(
            " ".join(check_cmd + ["|", "grep", "-q", "libusb-1.0-0"]))
        if not libusb_check[0]:
            print("Installing libusb-1.0-0...")
            success, _out = safe_system_call(
                " ".join(install_cmd + ["libusb-1.0-0"]))
            if success:
                print("libusb-1.0-0 installed successfully")
            else:
                print("Failed to install libusb-1.0-0")

        # Check other dependencies
        missing = check_dependencies()
        if missing:
            print("Missing dependencies: %s" % ", ".join(missing))
            for dep in missing:
                safe_system_call(" ".join(install_cmd + [dep]))

    except Exception as e:
        print("Package installation error: %s" % str(e))


# install_package() is no longer started at every boot (opkg update on each
# GUI start); it is available on demand.


def checkdir():
    """Create necessary directories"""
    directories = ["/usr/keys", "/usr/camscript"]

    for directory in directories:
        if not exists(directory):
            try:
                mkdir(directory)
                print("Created directory: %s" % directory)
            except Exception as e:
                print("Error creating directory %s: %s" % (directory, str(e)))


checkdir()

screenwidth = getDesktop(0).size()
if screenwidth.width() == 2560:
    skin_path = PLUGIN_PATH + "/res/skins/uhd/"
elif screenwidth.width() == 1920:
    skin_path = PLUGIN_PATH + "/res/skins/fhd/"
else:
    skin_path = PLUGIN_PATH + "/res/skins/hd/"

if exists("/usr/bin/apt-get"):
    skin_path = skin_path + "dreamOs/"

if not exists("/etc/clist.list"):
    with open("/etc/clist.list", "w"):
        print("/etc/clist.list has been created")
        system("chmod 755 /etc/clist.list")


def read_raw_current_cam():
    """Name saved in clist.list (or CurrentBhCamName), None when stopped."""
    for path in ("/etc/CurrentBhCamName", "/etc/clist.list"):
        if not exists(path):
            continue
        try:
            with open(path, "r") as f:
                lines = [x.strip() for x in f.read().splitlines() if x.strip()]
        except (IOError, OSError):
            continue
        name = lines[-1] if lines else ""
        return name if name and name != "None" else None
    return None


def read_current_cam():
    """Script id of the active cam (old OSD names are mapped to their script)."""
    return resolve_cam_id(read_raw_current_cam())


class m2list(MenuList):
    def __init__(self, list):
        MenuList.__init__(self, list, True, eListboxPythonMultiContent)
        if screenwidth.width() == 2560:
            self.l.setItemHeight(60)
            textfont = int(46)
            self.l.setFont(0, gFont("Regular", textfont))
        elif screenwidth.width() == 1920:
            self.l.setItemHeight(50)
            textfont = int(34)
            self.l.setFont(0, gFont("Regular", textfont))
        else:
            self.l.setItemHeight(50)
            textfont = int(22)
            self.l.setFont(0, gFont("Regular", textfont))


def show_list_1(h):
    res = [h]
    if screenwidth.width() == 2560:
        res.append(
            MultiContentEntryText(
                pos=(
                    2,
                    0),
                size=(
                    1000,
                    50),
                font=0,
                text=h,
                flags=RT_HALIGN_LEFT | RT_VALIGN_CENTER))
    elif screenwidth.width() == 1920:
        res.append(
            MultiContentEntryText(
                pos=(
                    2,
                    0),
                size=(
                    780,
                    40),
                font=0,
                text=h,
                flags=RT_HALIGN_LEFT | RT_VALIGN_CENTER))
    else:
        res.append(
            MultiContentEntryText(
                pos=(
                    2,
                    0),
                size=(
                    780,
                    40),
                font=0,
                text=h,
                flags=RT_HALIGN_LEFT | RT_VALIGN_CENTER))
    return res


def showlist(datal, list):
    plist = []
    for name in datal:
        plist.append(show_list_1(name))
    list.setList(plist)


CAM_KEYWORDS = (
    "oscam",
    "ncam",
    "cccam",
    "mgcamd",
    "gcam",
    "wicardd",
    "doscam",
    "gbox",
    "revcam",
    "movicam",
    "scam",
    "camd3",
    "evocamd",
    "rqcamd")


def cam_keyword(name):
    """'OSCam_11986-803' -> 'oscam' (None if unknown)."""
    low = (name or "").lower()
    for key in CAM_KEYWORDS:
        if key in low:
            return key
    return None


def cam_key_for(cam_id):
    """Softcam keyword of a cam id, from the file name or the OSD label."""
    return cam_keyword(cam_id) or cam_keyword(label_for(cam_id))


def running_cams():
    """{keyword: process name} of the softcam processes running now."""
    found = {}
    try:
        pids = [d for d in listdir("/proc") if d.isdigit()]
    except OSError:
        return found
    for pid in pids:
        try:
            with open("/proc/%s/comm" % pid, "r") as f:
                comm = f.read().strip()
        except (IOError, OSError):
            continue
        key = cam_keyword(comm)
        if key and key not in found:
            found[key] = comm
    return found


class ResourceMonitor:
    """System load + softcam processes for the main screen."""

    def __init__(self):
        self._cpu_prev = None

    def get_cam_resources(self, installed=None):
        try:
            cams = running_cams()
            names = ", ".join(sorted(cams.values()))
            if installed is None:
                cam_txt = "%d" % len(cams)
            else:
                cam_txt = "%d/%d" % (len(cams), installed)
            text = "Mem: %s | CPU: %s | %s: %s" % (
                self._get_memory_usage(), self._get_cpu_usage(), _("Running cams"), cam_txt)
            if names:
                text += " (%s)" % names
            return text
        except Exception as e:
            print("[ResourceMonitor] %s" % e)
            return "Stats error"

    @staticmethod
    def _get_memory_usage():
        try:
            total = avail = 0
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        total = int(line.split()[1])
                    elif line.startswith("MemAvailable:"):
                        avail = int(line.split()[1])
            if total and avail:
                return "%.0f%%" % ((total - avail) * 100.0 / total)
        except (IOError, OSError, ValueError):
            pass
        return "N/A"

    def _get_cpu_usage(self):
        """Real CPU % between two calls (/proc/stat), not the load average."""
        try:
            with open("/proc/stat", "r") as f:
                fields = [int(x) for x in f.readline().split()[1:]]
            idle = fields[3] + (fields[4] if len(fields) > 4 else 0)
            total = sum(fields)
            prev, self._cpu_prev = self._cpu_prev, (idle, total)
            if not prev or total == prev[1]:
                return "..."
            busy = 1.0 - float(idle - prev[0]) / (total - prev[1])
            return "%.0f%%" % max(0.0, min(100.0, busy * 100))
        except (IOError, OSError, ValueError, IndexError):
            return "N/A"


class ConfigBackupManager:
    """Configuration backup management (BACKUP_ROOT, mirrored full paths)."""

    def __init__(self):
        self.backup_dir = BACKUP_ROOT

    def create_backup(self, backup_name=None):
        return backup_configs(backup_name)

    def list_backups(self):
        try:
            return sorted((d for d in listdir(self.backup_dir)
                          if d.startswith("backup_")), reverse=True)
        except OSError:
            return []

    def backup_files(self, backup_name):
        """Original paths contained in a backup."""
        root = join(self.backup_dir, backup_name)
        files = []
        for dirpath, dirs, names in walk(root):
            for n in names:
                files.append(join(dirpath, n)[len(root):])
        return sorted(files)

    def restore_backup(self, backup_name):
        import shutil
        root = join(self.backup_dir, backup_name)
        if not exists(root):
            print("Backup path does not exist: %s" % root)
            return False, []
        restored = []
        for original in self.backup_files(backup_name):
            try:
                if not exists(dirname(original)):
                    makedirs(dirname(original))
                shutil.copy2(root + original, original)
                restored.append(original)
            except Exception as e:
                print("Error restoring %s: %s" % (original, e))
        return bool(restored), restored


class tvManager(Screen):

    def __init__(self, session):
        Screen.__init__(self, session)
        self.session = session
        global _session, runningcam
        runningcam = None
        _session = session
        self.resource_monitor = ResourceMonitor()
        self.backup_manager = ConfigBackupManager()
        skin = join(skin_path, "tvManager.xml")
        with codecs.open(skin, "r", encoding="utf-8") as f:
            self.skin = f.read()
        self.namelist = []
        self.softcamslist = []
        self.oldService = ""
        try:
            self.oldService = self.session.nav.getCurrentlyPlayingServiceReference()
        except BaseException:
            self.oldService = self.session.nav.getCurrentlyPlayingServiceOrGroup()
        self["NumberActions"] = NumberActionMap(
            ["NumberActions"],
            {
                "0": self.keyNumberGlobal,
                "1": self.keyNumberGlobal,
                "2": self.keyNumberGlobal,
                "3": self.keyNumberGlobal,
                "4": self.keyNumberGlobal,
                "5": self.keyNumberGlobal,
                "6": self.keyNumberGlobal,
                "7": self.keyNumberGlobal,
                "8": self.keyNumberGlobal,
                "9": self.keyNumberGlobal
            }
        )
        self["actions"] = ActionMap(
            [
                "OkCancelActions",
                "ColorActions",
                "EPGSelectActions",
                "MenuActions"
            ],
            {
                "ok": self.action,
                "cancel": self.close,
                "menu": self.configtv,
                "blue": self.Blue,
                "yellow": self.download,
                "green": self.action,
                "info": self.CfgInfo,
                "red": self.stop
            },
            -1
        )
        self.setTitle(_(TITLE_PLUG))
        self["title"] = Label(_(TITLE_PLUG))
        self["key_green"] = Label(_("Start"))
        self["key_yellow"] = Label(_("Cam Download"))
        self["key_red"] = Label(_("Stop"))
        self["key_blue"] = Label("Softcam")
        self["description"] = Label(
            _("Scanning and retrieval list softcam ..."))
        self["resource_label"] = Label()
        self["info"] = Label()
        self["list"] = List([])
        try:
            self["list"].onSelectionChanged.append(self.updateColorKeys)
        except AttributeError:
            pass
        self.curCam = None
        self.curCam = self.readCurrent()
        self.readScripts()
        self.BlueAction = "SOFTCAM"
        runningcam = "softcam"
        self.setBlueKey()
        self.timer = eTimer()
        try:
            self.timer_conn = self.timer.timeout.connect(self.cgdesc)
        except BaseException:
            self.timer.callback.append(self.cgdesc)
        self.timer.start(300, 1)

        self.EcmInfoPollTimer = eTimer()
        try:
            self.EcmInfoPollTimer_conn = self.EcmInfoPollTimer.timeout.connect(
                self.setEcmInfo)
        except BaseException:
            self.EcmInfoPollTimer.callback.append(self.setEcmInfo)
        self.EcmInfoPollTimer.start(1000)

        self["resource_label"] = Label()
        self["resource_label"].setText("Loading resources...")
        self.resource_timer = eTimer()
        try:
            self.resource_timer_conn = self.resource_timer.timeout.connect(
                self.update_resource_info)
        except BaseException:
            self.resource_timer.callback.append(self.update_resource_info)
        self.resource_timer.start(10000)
        self.resource_monitor._get_cpu_usage()  # first sample
        self.onLayoutFinish.append(self.update_resource_info)
        self.onLayoutFinish.append(self.autoCheckUpdate)
        self._closing = False
        self.onShown.append(self.ecm)
        self.onShown.append(self.startEcmInfoPollTimer)
        self.onShown.append(self.setBlueKey)
        self.onHide.append(self.stopEcmInfoPollTimer)
        self.onClose.append(self._stopTimers)

    def update_resource_info(self):
        try:
            text = self.resource_monitor.get_cam_resources(
                len(self.softcamslist))
        except Exception as e:
            text = "Error: %s" % e
        self["resource_label"].setText(text)

    def create_backup(self):
        """Create configuration backup"""
        backup_dir, backed_up = backup_configs()
        if backup_dir:
            message = "Backup created successfully!\nSaved %d files to:\n%s" % (
                len(backed_up), backup_dir)
            self.session.open(
                MessageBox,
                _(message),
                MessageBox.TYPE_INFO,
                timeout=10)
        else:
            self.session.open(
                MessageBox,
                _("Backup failed!"),
                MessageBox.TYPE_ERROR,
                timeout=5)

    def show_restore_menu(self):
        """Show menu to select backup to restore"""
        backups = self.backup_manager.list_backups()

        if not backups:
            self.session.open(
                MessageBox,
                _("No backups available!"),
                MessageBox.TYPE_INFO,
                timeout=5)
            return

        backup_list = []
        for backup in backups:
            backup_path = join(self.backup_manager.backup_dir, backup)
            if exists(backup_path):
                try:
                    stamp = datetime.strptime(backup, "backup_%Y%m%d_%H%M%S")
                    backup_time = stamp.strftime("%d/%m/%Y %H:%M:%S")
                except ValueError:
                    backup_time = backup
                count = len(self.backup_manager.backup_files(backup))
                backup_list.append(
                    ("Backup: %s (%d files)" %
                     (backup_time, count), backup))

        if not backup_list:
            self.session.open(
                MessageBox,
                _("No valid backups found!"),
                MessageBox.TYPE_INFO,
                timeout=5)
            return

        def backup_selected(selected_backup):
            if selected_backup:
                self.session.openWithCallback(
                    lambda result: self._execute_restore(
                        selected_backup[1],
                        result),
                    MessageBox,
                    _("Restore backup '%s'?\nThis will overwrite current configurations.") %
                    selected_backup[1],
                    MessageBox.TYPE_YESNO)

        self.session.openWithCallback(
            backup_selected,
            ChoiceBox,
            _("Select backup to restore:"),
            backup_list
        )

    def _execute_restore(self, backup_name, confirm):
        """Execute restore after confirmation"""
        if confirm:
            success, restored_files = self.backup_manager.restore_backup(
                backup_name)
            if success:
                message = _(
                    "Backup restored successfully!\nRestored files:\n- %s") % "\n- ".join(restored_files)
                self.session.open(
                    MessageBox,
                    message,
                    MessageBox.TYPE_INFO,
                    timeout=10)
                self.session.openWithCallback(
                    lambda result: self._restart_cam_after_restore(result),
                    MessageBox,
                    _("Restart softcam to apply restored configuration?"),
                    MessageBox.TYPE_YESNO
                )
            else:
                self.session.open(
                    MessageBox,
                    _("Backup restoration failed!"),
                    MessageBox.TYPE_ERROR,
                    timeout=5)

    def _restart_cam_after_restore(self, restart):
        """Restart cam after restore"""
        if restart:
            if self.curCam and self.curCam != "None":
                self.cmd1 = "/usr/camscript/" + self.curCam + ".sh cam_res &"
                system(self.cmd1)
                self.session.open(
                    MessageBox,
                    _("Softcam restarted with new configuration!"),
                    MessageBox.TYPE_INFO,
                    timeout=5)
            else:
                self.session.open(
                    MessageBox,
                    _("No active cam to restart!"),
                    MessageBox.TYPE_INFO,
                    timeout=5)

    def setBlueKey(self):
        global runningcam
        self.curCam = self.readCurrent()
        self["key_blue"].setText("Softcam")
        self.BlueAction = None
        if self.curCam is not None:
            cam_name = (
                "%s %s" %
                (self.curCam, label_for(
                    self.curCam))).lower()
            print("cam_name=", cam_name)
            cam_info = {
                "oscam": ("OSCAMINFO", "OScamInfo"),
                "cccam": ("CCCAMINFO", "CCcamInfo"),
                "movicam": ("MOVICAMINFO", "OScamInfo"),
                "ncam": ("NCAMINFO", "NcamInfo")
            }

            for key, (action, file_name) in cam_info.items():
                if key in cam_name:
                    print("%s detected in cam_name" % key)
                    runningcam = key
                    self.BlueAction = action
                    self["key_blue"].setText(action)
                    pyo_file = join(DATA_PATH, "%s.pyo" % file_name)
                    pyc_file = join(DATA_PATH, "%s.pyc" % file_name)
                    py_file = join(DATA_PATH, "%s.py" % file_name)
                    if exists(pyo_file) or exists(pyc_file) or exists(py_file):
                        print("exists %s" % file_name)
                    break

            print("[setBlueKey] self.curCam=", self.curCam)
            print("[setBlueKey] self.BlueAction=", self.BlueAction)
            print("[setBlueKey] runningcam=", runningcam)

    def Blue(self):
        print("[Blue] self.BlueAction:", self.BlueAction)
        cam_name = (
            "%s %s" %
            (self.curCam or "",
             label_for(
                 self.curCam))).lower()
        print("cam_name=", cam_name)
        try:
            if "oscam" in cam_name:
                self.open_oscam_info()
            elif "cccam" in cam_name:
                self.open_cccam_info()
            elif "ncam" in cam_name:
                self.open_ncam_info()
            elif "movicam" in cam_name:
                self.open_oscam_info()  # Use OSCamInfo for Movicam
            else:
                print("[Blue] Default action: CCcam")
                self.open_cccam_info()
        except Exception as e:
            print("[Blue] General Error:", e)
            self.session.open(
                MessageBox, _(
                    "Error opening cam info: %s" %
                    str(e)), MessageBox.TYPE_ERROR, timeout=5)

    def _open_plugin_screen(self, module_name, class_name, label):
        try:
            mod = __import__(
                "Plugins.Extensions.tvManager.data." +
                module_name,
                fromlist=[class_name])
            self.session.open(getattr(mod, class_name))
            return True
        except Exception as e:
            print("[tvManager] %s error: %s" % (label, e))
            import traceback
            traceback.print_exc()
            self.session.open(
                MessageBox,
                _("%s not available:\n%s") % (label, str(e)),
                MessageBox.TYPE_ERROR,
                timeout=8)
            return False

    def open_oscam_info(self):
        """Plugin OSCamInfo; the image's one only if ours fails to load."""
        self._open_plugin_screen("OScamStatus", "OSCamStatus", "OSCamInfo")

    def open_cccam_info(self):
        self._open_plugin_screen("CCcamInfo", "CCcamInfoMain", "CCcamInfo")

    def open_ncam_info(self):
        self._open_plugin_screen("OScamStatus", "NCamStatus", "NcamInfo")

    def keyNumberGlobal(self, number):
        print("[DEBUG] keyNumberGlobal CALLED with number: %s" % number)
        try:
            number = int(number)
            print("[DEBUG] Processing number: %d" % number)
            # Actions Map
            key_actions = {
                0: self.messagekd,
                1: self.open_cccam_info,
                2: self.open_oscam_info,
                3: self.open_ncam_info,
                4: self.create_backup,
                5: self.show_restore_menu,
                6: self.cleanup_system,
                7: self.update_oscam_codes,
                8: self.show_help,
                9: self.restart_gui
            }

            if number in key_actions:
                print("[DEBUG] Executing action for number: %d" % number)
                key_actions[number]()
            else:
                print("[DEBUG] No action defined for number: %d" % number)

        except Exception as e:
            print("[DEBUG] Error in keyNumberGlobal: %s" % str(e))

    def show_help(self):
        """Show help for quick keys"""
        help_text = _("""Number Key Shortcuts:
            0 - Update Softcam Keys
            1 - CCcam Info
            2 - OSCam Info
            3 - NCam Info
            4 - Create Backup
            5 - Restore Backup
            6 - Cleanup System
            7 - Update OSCam Codes
            8 - This Help
            Press OK to close""")
        self.session.open(
            MessageBox,
            help_text,
            MessageBox.TYPE_INFO,
            timeout=15)

    def show_resource_info(self):
        """Show system resource information"""
        try:
            mem_info, cpu_info = get_resource_info_safe()

            memory_usage = self._parse_memory_info(mem_info)
            cpu_usage = self._parse_cpu_info(cpu_info)
            disk_cmd = "df -h / | tail -1 | awk '{print $4\"/\"$2\" free (\"$5\" used)\"}'"
            success, disk_info = safe_system_call(disk_cmd, timeout=5)
            disk = disk_info.strip() if success else "N/A"
            cam_resources = self.resource_monitor.get_cam_resources()

            resource_text = _("""System Resources:
                Memory Used: %s
                CPU Load: %s
                Disk: %s
                Cam Resources: %s
                Press OK to close""") % (memory_usage, cpu_usage, disk, cam_resources)

            self.session.open(
                MessageBox,
                resource_text,
                MessageBox.TYPE_INFO,
                timeout=10)

        except Exception as e:
            print("Error getting resource info: %s" % str(e))
            self.session.open(
                MessageBox,
                _("Error getting resource information"),
                MessageBox.TYPE_ERROR,
                timeout=3)

    def quick_restart(self):
        """Quick restart of current softcam"""
        if not self.curCam or self.curCam == "None":
            self.session.open(MessageBox, _("No active cam to restart!"),
                              MessageBox.TYPE_ERROR, timeout=3)
            return

        self.session.openWithCallback(self._execute_quick_restart, MessageBox,
                                      _("Quick restart %s?") % self.curCam,
                                      MessageBox.TYPE_YESNO)

    def _execute_quick_restart(self, answer):
        """Execute quick restart after confirmation"""
        if answer:
            try:
                stop_cmd = "/usr/camscript/%s.sh cam_down &" % self.curCam
                success, _out = safe_system_call(stop_cmd)

                if success:
                    sleep(1)
                    start_cmd = "/usr/camscript/%s.sh cam_up &" % self.curCam
                    safe_system_call(start_cmd)

                    self.session.open(
                        MessageBox, _("%s restarted successfully!") %
                        self.curCam, MessageBox.TYPE_INFO, timeout=3)
                else:
                    self.session.open(MessageBox,
                                      _("Error stopping %s!") % self.curCam,
                                      MessageBox.TYPE_ERROR, timeout=3)

            except Exception as e:
                print("Quick restart error: %s" % str(e))
                self.session.open(MessageBox,
                                  _("Restart error: %s") % str(e),
                                  MessageBox.TYPE_ERROR, timeout=3)

    def cleanup_system(self):
        """System cleanup - direct version"""
        print("[DEBUG] Starting system cleanup")

        try:
            cleanup_temp_files()

            if exists("/usr/bin/apt-get"):
                system("apt-get clean &")
            else:
                system("opkg clean &")

            system("find /tmp -name \"*.log\" -mtime +7 -delete &")

            self["description"].setText(_("System cleanup completed!"))
            print("[DEBUG] System cleanup completed")

        except Exception as e:
            print("[DEBUG] Cleanup error: %s" % str(e))
            self["description"].setText(_("Cleanup error: %s") % str(e))

    def restart_gui(self):
        """GUI restart"""
        self.session.openWithCallback(self._execute_restart_gui, MessageBox,
                                      _("Restart GUI?"),
                                      MessageBox.TYPE_YESNO)

    def _execute_restart_gui(self, answer):
        """Execute GUI restart"""
        if answer:
            self.session.open(TryQuitMainloop, 3)

    def setEcmInfo(self):
        """Update ECM information with robust error handling"""
        try:
            if getattr(self, "ecminfo", None) is None:
                self.ecminfo = GetEcmInfo()
            newEcmFound, ecmInfo = self.ecminfo.getEcm()
            if newEcmFound:
                formatted_ecm = self.format_ecm_info(ecmInfo)
                self["info"].setText(formatted_ecm)
                self.last_valid_ecm = time.time()
            elif not newEcmFound:
                self.ecm()

        except Exception as e:
            print("Error in setEcmInfo: %s" % str(e))
            self.ecm()

    ECM_KEYS = (
        ("caid", "CAID"), ("pid", "PID"), ("prov", "Provider"), ("provid", "Provider"),
        ("provider", "Provider"), ("chid", "CHID"), ("system", "System"),
        ("reader", "Reader"), ("using", "Using"), ("from", "From"), ("address", "Address"),
        ("source", "Source"), ("protocol", "Protocol"), ("hops", "Hops"),
        ("ecm time", "ECM time"), ("response time", "ECM time"))

    def format_ecm_info(self, ecm_info):
        """Readable ECM summary (never shows control words)."""
        if not ecm_info:
            return _("No ECM data")
        values = {}
        raw = []
        for line in ecm_info:
            line = line.strip()
            if not line or line.lower().startswith(("cw0", "cw1", "cw ")):
                continue
            raw.append(line)
            if ":" in line:
                k, v = line.split(":", 1)
                values.setdefault(k.strip().lower(), v.strip())
        out, seen = [], set()
        for key, label in self.ECM_KEYS:
            if key in values and label not in seen and values[key]:
                seen.add(label)
                val = values[key]
                if label == "ECM time" and val.replace(".", "", 1).isdigit():
                    val = val + " s" if "." in val else val + " ms"
                out.append("%s: %s" % (label, val))
        text = "\n".join(out or raw[:8])
        return text or _("No ECM data")

    def ecm(self):
        """Fallback: read the newest ecm*.info directly."""
        from .data.GetEcmInfo import current_ecm_file
        path = current_ecm_file()
        if not exists(path):
            self["info"].setText(
                _("No ECM (clear channel or cam not decoding)"))
            return
        try:
            with open(path, "r") as f:
                lines = f.readlines()
            self["info"].setText(self.format_ecm_info(
                lines) if lines else _("ECM file empty"))
        except (IOError, OSError) as e:
            print("ECM read error: %s" % e)
            self["info"].setText(_("ECM read error"))

    def stopEcmInfoPollTimer(self):
        self.EcmInfoPollTimer.stop()

    # ---- automatic update check (home screen, once a day) ----
    def autoCheckUpdate(self):
        if not update_check_due():
            return
        fetch_async(
            b64decoder(installer_url),
            self._autoUpdateGot,
            self._autoUpdateError)

    def _autoUpdateError(self, error):
        print(
            "[tvManager] update check failed: %s" %
            error)   # retried next opening

    def _autoUpdateGot(self, data):
        mark_update_checked()
        if self._closing:
            return
        version, changelog = parse_installer(data)
        if version_tuple(__version__) >= version_tuple(version):
            return
        self["description"].setText(
            _("New version %s available - press INFO to update") %
            version)
        if not getattr(self, "shown", True):
            return   # a sub screen is open: the description line is enough
        self.session.openWithCallback(
            self._autoUpdateAnswer, MessageBox,
            _("tvManager %s is available (installed: %s).\n\n%s\n\nInstall now?") %
            (version, __version__, changelog),
            MessageBox.TYPE_YESNO, default=False, timeout=20)

    def _autoUpdateAnswer(self, answer):
        if answer:
            self.session.open(
                Console, _("Upgrading..."), cmdlist=[
                    plugin_update_cmd()], closeOnSuccess=False)

    def _stopTimers(self):
        self._closing = True
        for t in (self.EcmInfoPollTimer, self.resource_timer, self.timer):
            try:
                t.stop()
            except Exception:
                pass

    def startEcmInfoPollTimer(self):
        self.EcmInfoPollTimer.start(1000)

    def update_oscam_codes(self):
        """Tivusat reader keys: runs in the Console screen (GUI never blocked)."""
        script_path = join(PLUGIN_PATH, "data", "update_oscam_codes.sh")
        if not exists(script_path):
            self.session.open(
                MessageBox, _("Update script not found!\nPath: %s") %
                script_path, MessageBox.TYPE_ERROR, timeout=5)
            return
        self.session.open(
            Console, _("Update OSCam Tivusat codes"), [
                "/bin/sh %s" %
                shell_quote(script_path)], closeOnSuccess=False)

    def messagekd(self):
        """Update Softcam Keys"""
        print("[DEBUG] Opening Console for keys update")

        script = join(PLUGIN_PATH, "auto")
        if not access(script, X_OK):
            chmod(script, 493)
        if exists("/usr/keys/SoftCam.Key"):
            system("rm -rf /usr/keys/SoftCam.Key")

        cmd = script
        title = _("Installing Softcam Keys\nPlease Wait...")

        self.session.open(Console, title, [cmd], closeOnSuccess=False)

    def CfgInfo(self):
        self.session.open(InfoCfg)

    def configtv(self):
        from Plugins.Extensions.tvManager.data.datas import tv_config
        self.session.open(tv_config)

    def cgdesc(self):
        if len(self.namelist) >= 1:
            self["description"].setText(_("Select a cam to run ..."))
        else:
            self["description"].setText(_("Install Cam first!!!"))
            self.updateList()

    def getcont(self):
        cont = "Your Config:\n"
        arc = ""
        arkFull = ""
        libsssl = ""
        python = popen("python -V").read().strip("\n\r")
        arcx = popen("uname -m").read().strip("\n\r")
        libs = popen("ls -l /usr/lib/libss*.*").read().strip("\n\r")
        if arcx:
            arc = arcx
            print("arc= ", arc)
        if self.arckget():
            print("arkget= ", arkFull)
            arkFull = self.arckget()
        if libs:
            libsssl = libs
        cont += " ------------------------------------------ \n"
        cont += "Cpu: %s\nArchitecture info: %s\nPython V.%s\nLibssl(oscam):\n%s" % (
            arc, arkFull, python, libsssl)
        cont += " ------------------------------------------ \n"
        cont += "Button Info for Other Info\n"
        return cont

    def arckget(self):
        zarcffll = "by Lululla"
        try:
            if exists("/usr/bin/apt-get"):
                zarcffll = popen(
                    "dpkg --print-architecture | grep -iE 'arm|aarch64|mips|cortex|sh4|sh_4'").read().strip("\n\r")
            else:
                zarcffll = popen(
                    "opkg print-architecture | grep -iE 'arm|aarch64|mips|cortex|h4|sh_4'").read().strip("\n\r")
            return str(zarcffll)
        except Exception as e:
            print("Error ", e)

    def updateList(self):
        poPup = self.getcont()
        _session.open(MessageBox, poPup, MessageBox.TYPE_INFO, timeout=10)

    def download(self):
        self.session.open(GetipklistTv)
        self.onShown.append(self.readScripts)

    def getLastIndex(self):
        """Index in softcamslist of the cam that is currently active."""
        cur = (self.curCam or "").strip()
        if not cur or cur == "None":
            return None
        for idx, entry in enumerate(self.softcamslist):
            if entry[3] == cur:
                return idx
        return None

    def action(self):
        i = len(self.softcamslist)
        if i < 1:
            self.session.open(
                MessageBox,
                _("No softcams available!"),
                MessageBox.TYPE_ERROR,
                timeout=5)
            return

        try:
            self.oldService = self.session.nav.getCurrentlyPlayingServiceReference()
        except BaseException:
            self.oldService = self.session.nav.getCurrentlyPlayingServiceOrGroup()

        self.session.nav.stopService()
        self.last = self.getLastIndex()
        if self["list"].getCurrent():
            self.var = self["list"].getIndex()

            system("chmod 755 /etc/clist.list")
            system("chmod 755 /usr/camscript/*.*")
            curCam = self.readCurrent()
            if self.last is not None:
                try:
                    foldcurr = "/usr/bin/" + str(curCam)
                    foldscrpt = "/usr/camscript/" + str(curCam) + ".sh"
                    system("chmod 755 '%s'" % foldcurr)
                    system("chmod 755 '%s'" % foldscrpt)
                except OSError:
                    pass

                if self.last == self.var:
                    self.cmd1 = "/usr/camscript/" + \
                        self.softcamslist[self.var][3] + ".sh" + " cam_res &"
                    _session.open(
                        MessageBox,
                        _("Please wait..\nRESTART CAM"),
                        MessageBox.TYPE_INFO,
                        timeout=5)
                    system(self.cmd1)
                    sleep(1)
                else:
                    self.cmd1 = "/usr/camscript/" + \
                        self.softcamslist[self.last][3] + ".sh" + " cam_down &"
                    _session.open(
                        MessageBox,
                        _("Please wait..\nSTOP & RESTART CAM"),
                        MessageBox.TYPE_INFO,
                        timeout=5)
                    system(self.cmd1)
                    sleep(1)
                    self.cmd1 = "/usr/camscript/" + \
                        self.softcamslist[self.var][3] + ".sh" + " cam_up &"
                    system(self.cmd1)
            else:
                try:
                    self.cmd1 = "/usr/camscript/" + \
                        self.softcamslist[self.var][3] + ".sh" + " cam_up &"
                    _session.open(
                        MessageBox,
                        _("Please wait..\nSTART UP CAM"),
                        MessageBox.TYPE_INFO,
                        timeout=5)
                    system(self.cmd1)
                    sleep(1)
                except BaseException:
                    self.close()

            if self.last != self.var:
                try:
                    self.curCam = self.softcamslist[self.var][3]
                    self.writeFile()
                except BaseException:
                    self.close()

        self.session.nav.playService(self.oldService)
        self.EcmInfoPollTimer.start(1000)
        self.readScripts()

    def writeFile(self):
        """
        /etc/clist.list = active cam name (empty when stopped)
        /etc/startcam.sh = what to run at boot (always cam_up, never stop/restart)
        """
        name = (self.curCam or "").strip()
        if name == "None":
            name = ""
        with open("/etc/clist.list", "w") as clist:
            clist.write(name)
        if name:
            with open("/etc/startcam.sh", "w") as stcam:
                stcam.write(
                    "#!/bin/sh\n/usr/camscript/%s.sh cam_up &\n" %
                    name)
            chmod("/etc/startcam.sh", 0o755)
        elif exists("/etc/startcam.sh"):
            remove("/etc/startcam.sh")

    def stop(self):
        i = len(self.softcamslist)
        if i < 1:
            return

        global runningcam
        try:
            self.oldService = self.session.nav.getCurrentlyPlayingServiceReference()
        except BaseException:
            self.oldService = self.session.nav.getCurrentlyPlayingServiceOrGroup()

        self.session.nav.stopService()
        if self.curCam and self.curCam != "None":
            self.EcmInfoPollTimer.stop()
            self.last = self.getLastIndex()

            if self.last is not None:
                self.cmd1 = "/usr/camscript/" + \
                    self.softcamslist[self.last][3] + ".sh" + " cam_down &"
                system(self.cmd1)
                self.curCam = None
                self.writeFile()
                sleep(1)

                if exists(ECM_INFO):
                    remove(ECM_INFO)

                self.session.open(
                    MessageBox,
                    _("Please wait..\nSTOP CAM"),
                    MessageBox.TYPE_INFO,
                    timeout=5)
                self["info"].setText("CAM STOPPED")
                self.BlueAction = "SOFTCAM"
                runningcam = "softcam"
                self.readScripts()
        self.session.nav.playService(self.oldService)

    def readScripts(self):
        """
        Cam list from /usr/camscript/*.sh.
        Entry = (label, icon, status, cam_id): the label is the OSD="..." name,
        cam_id is the script file name without .sh and is what gets started.
        """
        try:
            raw = read_raw_current_cam()
            self.curCam = resolve_cam_id(raw)
            if raw and self.curCam and raw != self.curCam:
                # clist.list from an older version holds the OSD name
                self.writeFile()
            running = running_cams()
            png1 = LoadPixmap(cached=True, path=resolveFilename(
                SCOPE_PLUGINS, "Extensions/tvManager/res/img/actcam.png"))
            png2 = LoadPixmap(cached=True, path=resolveFilename(
                SCOPE_PLUGINS, "Extensions/tvManager/res/img/defcam.png"))
            entries = []
            for cam_id, label in camscripts():
                if cam_id == self.curCam:
                    key = cam_keyword(cam_id) or cam_keyword(label)
                    if key in running:
                        entries.append(
                            (0, (label, png1, _("(Active)"), cam_id)))
                    else:
                        entries.append(
                            (1, (label, png2, _("(Not running)"), cam_id)))
                else:
                    entries.append((2, (label, png2, "", cam_id)))
            entries.sort(key=lambda e: (e[0], e[1][0].lower()))
            self.softcamslist[:] = [e[1] for e in entries]
            self.namelist = [(e[1][0], e[1][2]) for e in entries]
            self["list"].setList(self.softcamslist)
            self.setBlueKey()
            self.updateColorKeys()
        except Exception as e:
            print("error scriptlist: ", e)

    def updateColorKeys(self):
        """GREEN = Start / Restart for the selected cam, RED only when something runs."""
        try:
            cur = self["list"].getCurrent()
            selected = cur[3] if cur else None
            running = running_cams()
            active_running = bool(
                self.curCam) and cam_key_for(
                self.curCam) in running
            if selected and selected == self.curCam and active_running:
                self["key_green"].setText(_("Restart"))
            else:
                self["key_green"].setText(_("Start"))
            self["key_red"].setText(
                _("Stop") if (
                    active_running or self.curCam) else "")
        except Exception as e:
            print("[tvManager] updateColorKeys: %s" % e)

    def readCurrent(self):
        return read_current_cam()

    """
    def autocam(self):
        current = None
        try:
            # clist = open("/etc/clist.list", "r")
            if sys.version_info[0] == 3:
                clist = open("/etc/clist.list", "r", encoding="UTF-8")
            else:
                clist = open("/etc/clist.list", "r")
            print("found list")
        except:
            return

        if clist is not None:
            for line in clist:
                current = line
            clist.close()
        print("current =", current)
        if os.path.isfile("/etc/autocam.txt") is False:
            if sys.version_info[0] == 3:
                alist = open("/etc/autocam.txt", "w", encoding="UTF-8")
            else:
                alist = open("/etc/autocam.txt", "w")
            alist.close()
        self.cleanauto()
        if sys.version_info[0] == 3:
            alist = open("/etc/autocam.txt", "a", encoding="UTF-8")
        else:
            alist = open("/etc/autocam.txt", "a")
        alist.write(self.oldService.toString() + "\n")
        # last = self.getLastIndex()
        alist.write(current + "\n")
        alist.close()
        self.session.openWithCallback(self.callback, MessageBox, _("Autocam assigned to the current channel"), type=1, timeout=10)
        return

    def cleanauto(self):
        delemu = "no"
        if os.path.isfile("/etc/autocam.txt") is False:
            return
        if sys.version_info[0] == 3:
            myfile = open("/etc/autocam.txt", "r", encoding="UTF-8")
        else:
            myfile = open("/etc/autocam.txt", "r")

        if sys.version_info[0] == 3:
            myfile2 = open("/etc/autocam2.txt", "w", encoding="UTF-8")
        else:
            myfile2 = open("/etc/autocam2.txt", "w")
        icount = 0
        for line in myfile.readlines():
            if line[:-1] == self.oldService.toString():
                delemu = "yes"
                icount = icount + 1
                continue
            if delemu == "yes":
                delemu = "no"
                icount = icount + 1
                continue
            myfile2.write(line)
            icount = icount + 1
        myfile.close()
        myfile2.close()
        system("rm /etc/autocam.txt")
        system("cp /etc/autocam2.txt /etc/autocam.txt")
        """

    def cancel(self):
        self.close()


class GetipklistTv(Screen):

    def __init__(self, session):
        self.session = session
        skin = join(skin_path, "GetipkTv.xml")
        with codecs.open(skin, "r", encoding="utf-8") as f:
            self.skin = f.read()
        Screen.__init__(self, session)
        self.names = []
        self.names_1 = []
        self.list = []
        self["list"] = MenuList([])
        self.setTitle(_(TITLE_PLUG))
        self["title"] = Label(_(TITLE_PLUG))
        self["description"] = Label(_("Getting the list, please wait ..."))
        self["paypal"] = Label()
        self["key_red"] = Button(_("Back"))
        self["key_green"] = Button(_("Load"))
        self["key_yellow"] = Button()
        self["key_blue"] = Button()
        self["key_green"].hide()
        if exists(FILE_XML):
            self["key_green"].show()
        self["key_yellow"].hide()
        self["key_blue"].hide()
        self.addon = "emu"
        self.url = ""
        self.xml = b64decode(ftpxml).decode('utf-8')
        self.icount = 0
        self.downloading = False
        self.timer = eTimer()
        if exists("/usr/bin/apt-get"):
            self.timer_conn = self.timer.timeout.connect(self._gotPageLoad)
        else:
            self.timer.callback.append(self._gotPageLoad)
        self.timer.start(500, 1)
        self["actions"] = ActionMap(
            [
                "OkCancelActions",
                "ColorActions"
            ],
            {
                "ok": self.okClicked,
                "cancel": self.close,
                "green": self.loadpage,
                "red": self.close
            },
            -1
        )
        self.onShown.append(self.pasx)

    def pasx(self):
        pass

    def updateList(self):
        payp = paypal()
        self["paypal"].setText(payp)

    def loadpage(self):
        """GREEN: use the local tvManager.xml instead of the online list."""
        if exists(FILE_XML):
            del self.names[:]
            del self.list[:]
            self["list"].l.setList(self.list)
            with open(FILE_XML, "r") as f:
                self.downloadxmlpage(f.read())

    def _gotPageLoad(self):
        self["description"].setText(_("Getting the list, please wait ..."))
        fetch_async(self.xml, self.downloadxmlpage, self.errorLoad)

    def downloadxmlpage(self, data):
        print("Downloading XML page...")
        self.xml = data
        self.list = []
        self.names = []
        try:
            if self.xml:
                print("Parsing XML...")
                self.xmlparse = minidom.parseString(self.xml)
                for plugins in self.xmlparse.getElementsByTagName("plugins"):
                    if not exists("/usr/bin/apt-get"):
                        if "deb" in str(plugins.getAttribute("cont")).lower():
                            continue

                    if exists("/usr/bin/apt-get"):
                        if "deb" not in str(
                                plugins.getAttribute("cont")).lower():
                            continue
                    self.names.append(str(plugins.getAttribute("cont")))
                print("have an Atv-PLi - etc..!!!", self.names)
                self["list"].l.setList(self.names)
                self["description"].setText(_("Please select ..."))
                self.downloading = True
        except Exception as e:
            print("Error during XML parsing:", e)
            self["description"].setText(
                _("Error processing server addons data"))

    def errorLoad(self, error):
        print("[GetipklistTv] %s" % error)
        self["description"].setText(
            _("Try again later ...") +
            "  (%s)" %
            str(error)[
                :80])
        self.downloading = False

    def okClicked(self):
        try:
            if self.downloading is True:
                selection = str(self["list"].getCurrent())
                self.session.open(GetipkTv, self.xmlparse, selection)
            else:
                self.close()
        except BaseException:
            return


class GetipkTv(Screen):
    def __init__(self, session, xmlparse, selection):
        Screen.__init__(self, session)
        self.session = session
        skin = join(skin_path, "GetipkTv.xml")
        with codecs.open(skin, "r", encoding="utf-8") as f:
            self.skin = f.read()
        self.xmlparse = xmlparse
        self.selection = selection
        self.list = []
        adlist = []
        for plugins in self.xmlparse.getElementsByTagName("plugins"):
            if str(plugins.getAttribute("cont")) == self.selection:
                for plugin in plugins.getElementsByTagName("plugin"):
                    adlist.append(str(plugin.getAttribute("name")))
                continue
        adlist.sort()
        self["list"] = MenuList(adlist)
        self.setTitle(_(TITLE_PLUG))
        self["title"] = Label(_(TITLE_PLUG))
        self["description"] = Label(_("Select and Install"))
        self["paypal"] = Label()
        self["key_red"] = Button(_("Back"))
        self["key_green"] = Button("Remove")
        self["key_yellow"] = Button("Restart")
        self["key_blue"] = Button()
        self["key_green"].hide()
        # self["key_yellow"].hide()
        self["key_blue"].hide()
        self["actions"] = ActionMap(
            [
                "OkCancelActions",
                "ColorActions"
            ],
            {
                "ok": self.message,
                "cancel": self.close,
                # "green": self.remove,
                "yellow": self.restart,
            },
            -1
        )
        self.onLayoutFinish.append(self.start)

    def start(self):
        pass

    def updateList(self):
        payp = paypal()
        self["paypal"].setText(payp)

    def message(self):
        self.session.openWithCallback(
            self.selclicked,
            MessageBox,
            _("Do you install this plugin ?"),
            MessageBox.TYPE_YESNO)

    def selclicked(self, result):
        if result:
            try:
                selection_country = self["list"].getCurrent()
                for plugins in self.xmlparse.getElementsByTagName("plugins"):
                    if str(plugins.getAttribute("cont")) == self.selection:
                        for plugin in plugins.getElementsByTagName("plugin"):
                            if str(
                                    plugin.getAttribute("name")) == selection_country:
                                self.com = str(
                                    plugin.getElementsByTagName("url")[0].childNodes[0].data)
                                self.dom = str(plugin.getAttribute("name"))
                                # test lululla
                                self.com = self.com.replace('"', "")
                                if ".deb" in self.com:
                                    if not exists("/usr/bin/apt-get"):
                                        self.session.open(
                                            MessageBox, _("Unknow Image!"), MessageBox.TYPE_INFO, timeout=5)
                                        return
                                    n2 = self.com.find("_", 0)
                                    self.dom = self.com[:n2]

                                if ".ipk" in self.com:
                                    if exists("/usr/bin/apt-get"):
                                        self.session.open(
                                            MessageBox, _("Unknow Image!"), MessageBox.TYPE_INFO, timeout=5)
                                        return
                                    n2 = self.com.find("_", 0)
                                    self.dom = self.com[:n2]
                                elif ".zip" in self.com:
                                    self.dom = self.com
                                elif ".tar" in self.com or ".gz" in self.com or "bz2" in self.com:
                                    self.dom = self.com
                                print("self.prombt self.com: ", self.com)
                                self.prombt()
                            else:
                                print("Return from prompt ")
                                self["description"].setText("Select")
                            continue
            except Exception as e:
                print("error prompt ", e)
                self["description"].setText("Error")
                return

    def prombt(self):
        url = str(self.com).strip()
        if not (url.startswith("https://") or url.startswith("http://")):
            self.session.open(MessageBox, _("Invalid download URL:\n%s") % url,
                              MessageBox.TYPE_ERROR, timeout=8)
            return
        # file name only from safe characters: it ends up in a shell command
        self.plug = sub(r"[^A-Za-z0-9._+-]", "_",
                        url.split("/")[-1].split("?")[0]) or "download"
        self.folddest = join("/tmp", self.plug)
        dest = shell_quote(self.folddest)
        name = self.plug.lower()
        if name.endswith(".deb"):
            install = "dpkg -i %s" % dest
        elif name.endswith(".ipk"):
            install = "opkg install --force-reinstall --force-overwrite %s" % dest
        elif name.endswith(".zip"):
            install = "unzip -o -q %s -d /" % dest
        elif name.endswith((".tar.gz", ".tgz")):
            install = "tar -xzf %s -C /" % dest
        elif name.endswith((".tar.bz2", ".tbz2", ".tbz")):
            install = "tar -xjf %s -C /" % dest
        elif name.endswith(".tar"):
            install = "tar -xf %s -C /" % dest
        else:
            self.session.open(
                MessageBox, _("Unknown package type:\n%s") %
                self.plug, MessageBox.TYPE_ERROR, timeout=8)
            return
        # certificate is checked; install only if the download succeeded
        cmd = (
            "rm -f %s; wget -U %s -O %s %s && %s; rc=$?; rm -f %s; "
            "[ $rc -ne 0 ] && echo 'Download/installation failed (if it is a certificate error: opkg install ca-certificates)'; exit $rc") % (dest,
                                                                                                                                              shell_quote(AgentRequest),
                                                                                                                                              dest,
                                                                                                                                              shell_quote(url),
                                                                                                                                              install,
                                                                                                                                              dest)
        print("cmd:", cmd)
        title = _("Installing %s\nPlease Wait...") % self.dom
        self.session.open(Console, title, [cmd], closeOnSuccess=False)

    def remove(self):
        self.session.openWithCallback(
            self.removenow,
            MessageBox,
            _("Do you want to remove?"),
            MessageBox.TYPE_YESNO)

    def removenow(self, answer=False):
        if answer:
            selection_country = self["list"].getCurrent()
            for plugins in self.xmlparse.getElementsByTagName("plugins"):
                if str(plugins.getAttribute("cont")) == self.selection:
                    for plugin in plugins.getElementsByTagName("plugin"):
                        if str(
                                plugin.getAttribute("name")) == selection_country:
                            self.com = str(
                                plugin.getElementsByTagName("url")[0].childNodes[0].data)
                            self.dom = str(plugin.getAttribute("name"))
                            # test lululla
                            self.com = self.com.replace('"', "")
                            cmd = ""

                            if ".deb" in self.com:
                                if not exists("/usr/bin/apt-get"):
                                    self.session.open(
                                        MessageBox, _("Unknow Image!"), MessageBox.TYPE_INFO, timeout=5)
                                    return
                                self.plug = self.com.split("/")[-1]
                                n2 = self.plug.find("_", 0)
                                self.dom = self.plug[:n2]
                                cmd = "dpkg -r " + self.dom  # + """
                                print("cmd deb remove:", cmd)
                            if ".ipk" in self.com:
                                if exists("/usr/bin/apt-get"):
                                    self.session.open(
                                        MessageBox, _("Unknow Image!"), MessageBox.TYPE_INFO, timeout=5)
                                    return
                                self.plug = self.com.split("/")[-1]
                                n2 = self.plug.find("_", 0)
                                self.dom = self.plug[:n2]
                                cmd = "opkg remove " + self.dom  # + """
                                print("cmd ipk remove:", cmd)

                            title = (_("Removing %s") % self.dom)
                            self.session.open(Console, _(title), [cmd])

    def restart(self):
        self.session.openWithCallback(
            self.restartnow,
            MessageBox,
            _("Do you want to restart Gui Interface?"),
            MessageBox.TYPE_YESNO)

    def restartnow(self, answer=False):
        if answer:
            self.session.open(TryQuitMainloop, 3)


class InfoCfg(Screen):
    def __init__(self, session):
        self.session = session
        skin = join(skin_path, "InfoCfg.xml")
        with codecs.open(skin, "r", encoding="utf-8") as f:
            self.skin = f.read()
        Screen.__init__(self, session)
        self.list = []
        self.setTitle(_(TITLE_PLUG))
        self["list"] = Label()
        self["actions"] = ActionMap(
            [
                "OkCancelActions",
                "DirectionActions",
                "HotkeyActions",
                "InfobarEPGActions",
                "ColorActions",
                "ChannelSelectBaseActions"
            ],
            {
                "ok": self.close,
                "back": self.close,
                "cancel": self.close,
                "yellow": self.update_me,
                "green": self.update_dev,
                "blue": self.toggleContent,
                "yellow_long": self.update_dev,
                "info_long": self.update_dev,
                "infolong": self.update_dev,
                "showEventInfoPlugin": self.update_dev,
                "red": self.close,
                "up": self.pageUp,
                "down": self.pageDown
            },
            -1
        )
        self["paypal"] = Label()
        self["key_red"] = Button(_("Back"))
        self["key_green"] = Button(_("Force Update"))
        self["key_yellow"] = Button(_("Update"))
        self["key_blue"] = Button(_("Resources"))
        self["key_green"].hide()
        self["key_yellow"].hide()
        self["key_blue"].show()

        self.Update = False
        self.current_content = "help"  # help, resources, system
        self.timer = eTimer()
        if exists("/usr/bin/apt-get"):
            self.timer_conn = self.timer.timeout.connect(self.check_vers)
        else:
            self.timer.callback.append(self.check_vers)
        self.timer.start(500, 1)
        self["title"] = Label(_(TITLE_PLUG))
        self.onShown.append(self.updateList)

    def check_vers(self):
        """Read version/changelog from installer.sh in background."""
        fetch_async(
            b64decoder(installer_url),
            self._got_version,
            self._version_error)

    def _version_error(self, error):
        print("[InfoCfg] version check failed: %s" % error)
        self["key_green"].show()

    def _got_version(self, data):
        mark_update_checked()
        remote_version, remote_changelog = parse_installer(data)
        self.new_version = remote_version
        self.new_changelog = remote_changelog
        if version_tuple(__version__) < version_tuple(remote_version):
            self.Update = True
            self["key_yellow"].show()
            self.session.open(
                MessageBox,
                _("New version %s is available\n\nChangelog: %s\n\nPress yellow button to update.") %
                (self.new_version, self.new_changelog),
                MessageBox.TYPE_INFO,
                timeout=5)
        self["key_green"].show()

    def update_me(self):
        if self.Update is True:
            self.session.openWithCallback(
                self.install_update,
                MessageBox,
                _("New version %s is available.\n\nChangelog: %s \n\nInstall now?") %
                (self.new_version,
                 self.new_changelog),
                MessageBox.TYPE_YESNO)
        else:
            self.session.open(
                MessageBox,
                _("You have the latest version!"),
                MessageBox.TYPE_INFO,
                timeout=3)

    def update_dev(self):
        fetch_async(
            b64decoder(developer_url),
            self._got_dev,
            self._version_error)

    def _got_dev(self, data):
        try:
            remote_date = json.loads(data)["pushed_at"]
            remote_date = datetime.strptime(
                remote_date, "%Y-%m-%dT%H:%M:%SZ").strftime("%Y-%m-%d")
        except Exception as e:
            self._version_error(e)
            return
        self.session.openWithCallback(
            self.install_update,
            MessageBox,
            _("Install developer update (%s)?") %
            remote_date,
            MessageBox.TYPE_YESNO)

    def install_update(self, answer=False):
        if answer:
            self.session.open(
                Console,
                "Upgrading...",
                cmdlist=[plugin_update_cmd()],
                finishedCallback=self.myCallback,
                closeOnSuccess=False)
        else:
            self.session.open(
                MessageBox,
                _("Update Aborted!"),
                MessageBox.TYPE_INFO,
                timeout=3)

    def myCallback(self, result=None):
        print("result:", result)
        return

    def get_help_content(self):
        """Compact help content"""
        help_text = _("""QUICK HELP - SOFTCOM MANAGER
            SHORTCUT KEYS:
            0-Keys Update  1-CCcam Info
            2-OSCam Info   3-NCam Info
            4-Create Bkp   5-Restore Bkp
            6-Cleanup      7-Update OSCam Codes
            8-This Help    9-Restart GUI

            CONFIG PATHS:
            CCcam: /etc/CCcam.cfg
            OScam: /etc/tuxbox/config/oscam.server
            NCam: /etc/tuxbox/config/ncam.server
            Keys: /usr/keys/SoftCam.Key

            BLUE BUTTON: Opens active cam info
            GREEN: Start/Restart cam
            RED: Stop cam
            YELLOW: Download cams""")
        return help_text

    def get_resource_content(self):
        """System resource content"""
        try:
            # Basic system info
            arc = popen("uname -m").read().strip() or "N/A"
            python = popen("python -V").read().strip() or "N/A"

            # Memory info
            memory = "N/A"
            if exists("/proc/meminfo"):
                with open("/proc/meminfo", "r") as f:
                    content = f.read()
                    if "MemTotal" in content and "MemAvailable" in content:
                        # Simplified memory calculation
                        pass
            # Disk info
            disk = "N/A"
            success, disk_info = safe_system_call(
                "df -h / | tail -1 | awk '{print $4\"/\"$2\" (\"$5\" used)\"}'", timeout=3)
            if success:
                disk = disk_info.decode().strip() if isinstance(
                    disk_info, bytes) else disk_info.strip()
            resource_text = _("""SYSTEM RESOURCES
                Architecture: %s
                Python: %s
                Memory: %s
                Disk: %s
                ACTIVE CAM: %s""") % (arc, python, memory, disk, self.get_active_cam())
            return resource_text

        except Exception as e:
            return _("Error loading system info: " + str(e))

    def get_system_content(self):
        """System information content"""
        try:
            arc = popen("uname -m").read().strip() or "N/A"
            python = popen("python -V").read().strip() or "N/A"
            arch_info = self.arckget() or "N/A"
            libssl = "N/A"
            success, libs = safe_system_call(
                "ls -1 /usr/lib/libssl.so* 2>/dev/null | head -1", timeout=3)
            if success and libs:
                libssl = libs.decode().strip() if isinstance(libs, bytes) else libs.strip()
            system_text = _("""SYSTEM INFORMATION
                CPU Arch: %s
                Platform: %s
                Python: %s
                LibSSL: %s
                Image: %s""") % (arc, arch_info, python, libssl, self.get_image_info())
            return system_text
        except Exception as e:
            return _("Error loading system information: " + str(e))

    def get_active_cam(self):
        """Get active cam name"""
        try:
            if hasattr(
                    self,
                    'session') and hasattr(
                    self.session,
                    'softcam_manager'):
                cam = self.session.softcam_manager.curCam
                return label_for(cam) if cam else "None"
            return "None"
        except BaseException:
            return "None"

    def get_image_info(self):
        """Get image information"""
        try:
            if exists("/etc/issue"):
                with open("/etc/issue", "r") as f:
                    return f.read().strip()
            elif exists("/etc/image-version"):
                with open("/etc/image-version", "r") as f:
                    return f.read().strip()
            return "Unknown"
        except BaseException:
            return "Unknown"

    def arckget(self):
        """Get architecture information"""
        try:
            if exists("/usr/bin/apt-get"):
                return popen(
                    "dpkg --print-architecture").read().strip() or "N/A"
            else:
                return popen(
                    "opkg print-architecture | head -1").read().strip() or "N/A"
        except BaseException:
            return "N/A"

    def toggleContent(self):
        """Switch between help, resources and system with BLUE key"""
        contents = ["help", "resources", "system"]
        current_index = contents.index(self.current_content)
        self.current_content = contents[(current_index + 1) % len(contents)]
        self.updateList()

    def updateList(self):
        """Update displayed content"""
        payp = paypal()
        self["paypal"].setText(payp)

        if self.current_content == "help":
            content = self.get_help_content()
            self["key_blue"].setText(_("Resources"))
        elif self.current_content == "resources":
            content = self.get_resource_content()
            self["key_blue"].setText(_("System"))
        else:  # system
            content = self.get_system_content()
            self["key_blue"].setText(_("Help"))

        self["list"].setText(content)

    def pageUp(self):
        """Scroll up - change content"""
        contents = ["help", "resources", "system"]
        current_index = contents.index(self.current_content)
        self.current_content = contents[(current_index - 1) % len(contents)]
        self.updateList()

    def pageDown(self):
        """Scroll down - change content"""
        contents = ["help", "resources", "system"]
        current_index = contents.index(self.current_content)
        self.current_content = contents[(current_index + 1) % len(contents)]
        self.updateList()


def autostartsoftcam(reason, session=None, **kwargs):
    """Simplified autostart without timeout"""
    print("[Softcam] Autostart initiated")

    if reason == 0 and session is not None:
        print("Autostart reason: 0")

        try:
            # Backup dccamd file if exists
            if exists("/etc/init.d/dccamd"):
                system("mv /etc/init.d/dccamd /etc/init.d/dccamdOrig &")

            # Create symbolic links if needed
            links = [
                ("/var/bin", "/usr/bin"),
                ("/var/keys", "/usr/keys"),
                ("/var/scce", "/usr/scce"),
                ("/var/script", "/usr/script")
            ]

            for link, target in links:
                if not islink(link):
                    system("ln -sf %s %s" % (target, link))

            cam = read_current_cam()
            script = "/usr/camscript/%s.sh" % cam if cam else ""
            if script and exists(script):
                print("[Softcam] starting %s" % cam)
                system("/bin/sh %s cam_up &" % shell_quote(script))
            elif exists("/etc/startcam.sh"):
                system("/bin/sh /etc/startcam.sh &")
            else:
                print("[Softcam] no cam selected, nothing to start")

            # CCcam Prio Maker (option "CCPrioMaker autostart" in CCcamInfo)
            try:
                from .data import CCcamPrioMaker
                CCcamPrioMaker.CCPrioMakerAutostart(session)
            except Exception as e:
                print("[Softcam] CCPrioMaker autostart: %s" % e)

        except Exception as e:
            print("Autostart error: %s" % str(e))


def main(session, **kwargs):
    try:
        session.open(tvManager)
    except Exception as e:
        print("Error in main: %s" % str(e))
        import traceback
        traceback.print_exc()


def startConfig(session, **kwargs):
    session.open(tvManager)


def mainmenu(menu_id):
    if menu_id == "setup":
        return [
            (
                _("Softcam Manager"),
                startConfig,
                "Softcam Manager",
                50
            )
        ]
    else:
        return []


def Plugins(**kwargs):
    # ICONPIC = "logo.png"
    return [
        PluginDescriptor(
            name=_(NAME_PLUG),
            where=PluginDescriptor.WHERE_MENU,
            fnc=mainmenu),
        PluginDescriptor(
            name=_(NAME_PLUG),
            description=_(TITLE_PLUG),
            where=[
                PluginDescriptor.WHERE_AUTOSTART,
                PluginDescriptor.WHERE_SESSIONSTART],
            needsRestart=True,
            fnc=autostartsoftcam,
        ),
        PluginDescriptor(
            name=_(NAME_PLUG),
            description=_(TITLE_PLUG),
            where=PluginDescriptor.WHERE_PLUGINMENU,
            icon=ICONPIC,
            fnc=main),
        PluginDescriptor(
            name=_(NAME_PLUG),
            description=_(TITLE_PLUG),
            where=PluginDescriptor.WHERE_EXTENSIONSMENU,
            fnc=main),
    ]
