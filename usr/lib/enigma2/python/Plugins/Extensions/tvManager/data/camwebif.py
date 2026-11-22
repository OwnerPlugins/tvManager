#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
Shared OSCam / NCam webif access for OScamInfo.py and NcamInfo.py.

Finds the running cam's config, reads httpport/httpuser/httppwd/httpallowed
and talks to <namebin>api.html on localhost, the same way the image's own
OScamInfo does (e.g. http://127.0.0.1:8888).
"""
from __future__ import print_function

import socket
import ssl
import sys
from glob import glob
from os import listdir
from os.path import basename, isdir, isfile, join

PY3 = sys.version_info.major >= 3

if PY3:
    from urllib.request import (
        build_opener, HTTPHandler, HTTPSHandler, Request,
        HTTPPasswordMgrWithDefaultRealm, HTTPDigestAuthHandler,
        HTTPBasicAuthHandler)
    from urllib.parse import quote_plus
    from urllib.error import URLError, HTTPError
else:
    from urllib2 import (
        build_opener, HTTPHandler, HTTPSHandler, Request, URLError, HTTPError,
        HTTPPasswordMgrWithDefaultRealm, HTTPDigestAuthHandler,
        HTTPBasicAuthHandler)
    from urllib import quote_plus

TIMEOUT = 5

CONF_DIRS = [
    "/etc/tuxbox/config",
    "/etc/tuxbox/config/{n}",
    "/etc/tuxbox/config/{n}-emu",
    "/etc/tuxbox/config/{n}-stable",
    "/etc/tuxbox/config/{n}-trunk",
    "/etc/tuxbox/config/{n}-smod",
    "/var/tuxbox/config",
    "/var/tuxbox/config/{n}",
    "/usr/keys",
    "/var/keys",
    "/etc",
]


def running_cam_args(namebin):
    """
    Command lines of running processes whose binary name contains namebin
    (oscam, oscam-emu, oscam_cardreader, ...). Works whoever started the cam.
    """
    found = []
    try:
        pids = [d for d in listdir("/proc") if d.isdigit()]
    except OSError:
        return found
    for pid in pids:
        try:
            with open("/proc/%s/cmdline" % pid, "rb") as f:
                raw = f.read()
        except (IOError, OSError):
            continue
        args = [a.decode("utf-8", "ignore") for a in raw.split(b"\0") if a]
        if not args:
            continue
        exe = basename(args[0]).lower()
        if namebin in exe and not exe.endswith(
                (".py", ".sh")) and "info" not in exe:
            found.append(args)
    return found


def _arg_value(args, short, long_):
    for i, a in enumerate(args):
        if a in (short, long_) and i + 1 < len(args):
            return args[i + 1]
        if a.startswith(long_ + "="):
            return a.split("=", 1)[1]
        if a.startswith(short) and len(a) > len(
                short) and not a.startswith("--"):
            return a[len(short):]
    return None


def cam_dirs_from_process(namebin):
    """(confdir, tmpdir) taken from -c / -t of the running cam, if given."""
    for args in running_cam_args(namebin):
        confdir = _arg_value(args, "-c", "--config-dir")
        tmpdir = _arg_value(args, "-t", "--temp-dir")
        return (confdir.rstrip("/") if confdir else None,
                tmpdir.rstrip("/") if tmpdir else None)
    return None, None


def _version_file(namebin):
    """Return the path of <namebin>.version written by the running cam."""
    candidates = []
    _confdir, tmpdir = cam_dirs_from_process(namebin)
    if tmpdir:
        candidates.append(join(tmpdir, "%s.version" % namebin))
        candidates += sorted(glob(join(tmpdir, "*.version")))
    candidates.append("/tmp/.%s/%s.version" % (namebin, namebin))
    candidates += sorted(glob("/tmp/.*/%s.version" % namebin))
    candidates += sorted(glob("/tmp/*/%s.version" % namebin))
    candidates += sorted(glob("/var/tmp/.*/%s.version" % namebin))
    for path in candidates:
        if isfile(path):
            return path
    return None


def read_version_info(namebin):
    """Parse <namebin>.version. Returns dict (empty if cam not running)."""
    info = {}
    path = _version_file(namebin)
    if not path:
        return info
    try:
        with open(path, "r") as f:
            for line in f:
                if ":" not in line:
                    continue
                key, val = line.split(":", 1)
                key = key.strip().lower()
                val = val.strip()
                if key == "web interface support":
                    info["webif"] = (val.lower() == "yes")
                elif key == "webifport":
                    info["port"] = val
                elif key == "configdir":
                    info["confdir"] = val.rstrip("/")
                elif key == "ipv6 support":
                    info["ipv6"] = (val.lower() == "yes")
                elif key == "version":
                    info["version"] = val
    except (IOError, OSError) as e:
        print("[camwebif] cannot read %s: %s" % (path, e))
    return info


def find_conf(namebin, confdir=None):
    """Return the full path of <namebin>.conf or None."""
    name = "%s.conf" % namebin
    dirs = []
    if confdir:
        dirs.append(confdir)
    dirs += [d.format(n=namebin) for d in CONF_DIRS]
    for d in dirs:
        path = join(d, name)
        if isdir(d) and isfile(path):
            return path
    return None


def read_webif_conf(conf):
    """Read the [webif] section of oscam.conf/ncam.conf (comments ignored)."""
    values = {}
    section = None
    try:
        with open(conf, "r") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or line.startswith(";"):
                    continue
                if line.startswith("[") and line.endswith("]"):
                    section = line[1:-1].strip().lower()
                    continue
                if section != "webif" or "=" not in line:
                    continue
                key, val = line.split("=", 1)  # passwords may contain "="
                values[key.strip().lower()] = val.strip()
    except (IOError, OSError) as e:
        print("[camwebif] cannot read %s: %s" % (conf, e))
    return values


def _ip_to_int(ip):
    parts = ip.strip().split(".")
    if len(parts) != 4:
        return None
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    if any(n < 0 or n > 255 for n in nums):
        return None
    return (nums[0] << 24) | (nums[1] << 16) | (nums[2] << 8) | nums[3]


def ip_allowed(ip, allowed):
    """True if IPv4 ip is inside the httpallowed list (a,b-c,...)."""
    target = _ip_to_int(ip)
    if target is None:
        return False
    for entry in allowed.split(","):
        entry = entry.strip()
        if not entry or ":" in entry:  # skip IPv6 entries
            continue
        if "-" in entry:
            lo, hi = entry.split("-", 1)
            lo, hi = _ip_to_int(lo), _ip_to_int(hi)
            if lo is not None and hi is not None and lo <= target <= hi:
                return True
        elif _ip_to_int(entry) == target:
            return True
    return False


def get_webif_settings(namebin):
    """
    Work out how to reach the local webif.
    Returns (settings_dict, None) or (None, error_message).
    """
    vinfo = read_version_info(namebin)
    proc_confdir, _tmp = cam_dirs_from_process(namebin)
    running = bool(vinfo) or bool(running_cam_args(namebin))
    if not running:
        return None, "%s is not running (no process and no %s.version found)" % (
            namebin.upper(), namebin)
    if vinfo.get("webif") is False:
        return None, "%s was built without web interface support" % namebin.upper()

    conf = find_conf(namebin, vinfo.get("confdir") or proc_confdir)
    web = read_webif_conf(conf) if conf else {}

    port = web.get("httpport") or vinfo.get("port") or ""
    use_ssl = port.startswith("+")
    port = port.lstrip("+").strip()
    if not port or port == "0":
        return None, "%s webif is disabled (httpport = 0 or missing in %s)" % (
            namebin.upper(), conf or "%s.conf" % namebin)

    host = "127.0.0.1"
    allowed = web.get("httpallowed", "")
    if allowed and not ip_allowed("127.0.0.1", allowed):
        if "::1" in allowed and vinfo.get("ipv6"):
            host = "[::1]"
        else:
            print("[camwebif] 127.0.0.1 not in httpallowed=%s" % allowed)

    return {
        "proto": "https" if use_ssl else "http",
        "host": host,
        "port": port,
        "user": web.get("httpuser", ""),
        "pwd": web.get("httppwd", ""),
        "conf": conf,
        "allowed": allowed,
    }, None


def build_url(settings, namebin, part=None, reader=None, fmt="html", extra=""):
    """fmt: "html" (XML answer), "json" or "xml"."""
    url = "%s://%s:%s/%sapi.%s?part=%s" % (
        settings["proto"], settings["host"], settings["port"], namebin,
        fmt, part or "status")
    if reader is not None:
        url += "&label=%s" % quote_plus(reader)
    return url + extra


def fetch(settings, namebin, part=None, reader=None, fmt="html", extra=""):
    """
    GET <namebin>api.html. Returns (True, text) or (False, error_message).
    Never raises, never blocks longer than TIMEOUT seconds.
    """
    url = build_url(settings, namebin, part, reader, fmt, extra)
    handlers = [HTTPHandler()]
    if settings["proto"] == "https":
        # Local webif only: OSCam uses a self-signed certificate.
        try:
            ctx = ssl._create_unverified_context()
            handlers.append(HTTPSHandler(context=ctx))
        except Exception:
            handlers.append(HTTPSHandler())
    if settings.get("user"):
        pwman = HTTPPasswordMgrWithDefaultRealm()
        base = "%s://%s:%s/" % (
            settings["proto"], settings["host"], settings["port"])
        pwman.add_password(
            None,
            base,
            settings["user"],
            settings.get(
                "pwd",
                ""))
        handlers.append(HTTPDigestAuthHandler(pwman))  # OSCam uses Digest
        handlers.append(HTTPBasicAuthHandler(pwman))
    opener = build_opener(*handlers)  # local opener, not installed globally
    try:
        resp = opener.open(Request(url), timeout=TIMEOUT)
        data = resp.read()
        resp.close()
    except HTTPError as e:
        if e.code == 401:
            msg = "login refused (check httpuser/httppwd in %s)" % (
                settings.get("conf") or "%s.conf" % namebin)
        elif e.code == 403:
            msg = "access denied: add 127.0.0.1 to httpallowed in %s" % (
                settings.get("conf") or "%s.conf" % namebin)
        else:
            msg = "HTTP error %s" % e.code
        return False, "%s [%s]" % (msg, url)
    except URLError as e:
        return False, "cannot connect: %s [%s]" % (
            getattr(e, "reason", e), url)
    except socket.timeout:
        return False, "timeout after %ss [%s]" % (TIMEOUT, url)
    except Exception as e:
        return False, "error: %s [%s]" % (e, url)

    if not isinstance(data, str):
        data = data.decode("utf-8", "ignore")
    head = data.lstrip()[:500]
    if fmt == "json":
        if not head.startswith("{"):
            return False, "unexpected answer (not JSON) [%s]" % url
    elif "<?xml" not in head[:200] and "<%s" % namebin not in head:
        return False, "unexpected answer (not XML) [%s]" % url
    return True, data
