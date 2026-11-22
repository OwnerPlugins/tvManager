#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
Small helpers used by tvManager.

The old Utils.py (2200 lines, copied from other plugins) imported IMDb/TMDB,
created an AspectManager and changed config.movielist at import time,
slowing down and touching the image for nothing. Only what tvManager uses
is kept here.
"""
from __future__ import print_function

import base64
import gzip
import sys
from io import BytesIO
from random import choice

PY3 = sys.version_info[0] >= 3

if PY3:
    from urllib.request import Request, urlopen
else:
    from urllib2 import Request, urlopen

ListAgent = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.6422.112 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.6422.112 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]


def RequestAgent():
    return choice(ListAgent)


def b64encoder(source):
    if PY3 and not isinstance(source, bytes):
        source = source.encode("utf-8")
    return base64.b64encode(source).decode("utf-8")


def b64decoder(data):
    """Base64 decode with padding correction; '' on error."""
    data = str(data).strip()
    pad = len(data) % 4
    if pad == 1:
        return ""
    if pad:
        data += "=" * (4 - pad)
    try:
        decoded = base64.b64decode(data)
        return decoded.decode("utf-8") if PY3 else decoded
    except Exception as e:
        print("Base64 decoding error: %s" % e)
        return ""


def checkStr(text, encoding="utf8"):
    if PY3:
        if isinstance(text, bytes):
            text = text.decode(encoding, "ignore")
    elif isinstance(text, unicode):  # noqa: F821 (Python 2 only)
        text = text.encode(encoding)
    return text


def checkGZIP(url, timeout=10):
    """Download url as text, gzip handled. None on error."""
    try:
        response = urlopen(
            Request(
                url,
                headers={
                    "User-Agent": "Enigma2 - Plugin"}),
            timeout=timeout)
        data = response.read()
        if response.info().get("Content-Encoding") == "gzip":
            data = gzip.GzipFile(fileobj=BytesIO(data)).read()
        response.close()
        return data.decode("utf-8", "ignore") if PY3 else data
    except Exception as e:
        print("checkGZIP %s: %s" % (url, e))
        return None


def getUrl(url, timeout=10):
    """Download url as text ('' on error). Certificates are verified."""
    try:
        response = urlopen(
            Request(
                url,
                headers={
                    "User-Agent": RequestAgent()}),
            timeout=timeout)
        data = response.read()
        response.close()
        return data.decode("utf-8", "ignore") if PY3 else data
    except Exception as e:
        print("getUrl %s: %s" % (url, e))
        return ""
