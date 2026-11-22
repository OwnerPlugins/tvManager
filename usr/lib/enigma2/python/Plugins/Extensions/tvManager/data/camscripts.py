# -*- coding: utf-8 -*-
"""
Camscripts in /usr/camscript.

A cam is identified by its script file name without ".sh"
(e.g. /usr/camscript/Oscam_11986.sh -> "Oscam_11986"). The OSD="..." line is
only the label shown in the list, so a cam still starts when the label and the
file name differ.
"""
from os import listdir
from os.path import isfile, join

CAMSCRIPT_DIR = "/usr/camscript"


def osd_label(path):
    """Value of the OSD= line of a script, or None."""
    try:
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if line.startswith("OSD"):
                    value = line.split("=", 1)[-1].strip().strip('"').strip("'")
                    return value or None
    except (IOError, OSError, UnicodeDecodeError):
        pass
    return None


def camscripts():
    """[(cam_id, label)] of every *.sh in /usr/camscript, sorted by label."""
    result = []
    try:
        names = listdir(CAMSCRIPT_DIR)
    except OSError:
        return result
    for fname in names:
        if not fname.endswith(".sh"):
            continue
        path = join(CAMSCRIPT_DIR, fname)
        if not isfile(path):
            continue
        cam_id = fname[:-3]
        result.append((cam_id, osd_label(path) or cam_id))
    result.sort(key=lambda x: x[1].lower())
    return result


def script_path(cam_id):
    return join(CAMSCRIPT_DIR, "%s.sh" % cam_id)


def resolve_cam_id(name):
    """
    Script id for a saved name. Older versions saved the OSD label in
    /etc/clist.list, so a label is mapped back to its script.
    """
    name = (name or "").strip()
    if not name or name == "None":
        return None
    if isfile(script_path(name)):
        return name
    for cam_id, label in camscripts():
        if label == name:
            return cam_id
    return name


def label_for(cam_id):
    """OSD label of a cam id (the id itself if unknown)."""
    if not cam_id:
        return ""
    return osd_label(script_path(cam_id)) or cam_id
