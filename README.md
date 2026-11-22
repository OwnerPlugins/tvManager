<h1 align="center">🚀 tvManager (Softcam Manager)</h1>

[![Version](https://img.shields.io/badge/Version-3.7-blue.svg)](https://github.com/Belfagor2005/tvManager)
[![Enigma2](https://img.shields.io/badge/Enigma2-Plugin-ff6600.svg)](https://www.enigma2.net)
[![Python](https://img.shields.io/badge/Python-2.7%2B-blue.svg)](https://www.python.org)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-green.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python package](https://github.com/Belfagor2005/tvManager/actions/workflows/pylint.yml/badge.svg)](https://github.com/Belfagor2005/tvManager/actions/workflows/pylint.yml)
[![Ruff Status](https://github.com/Belfagor2005/tvManager/actions/workflows/ruff.yml/badge.svg)](https://github.com/Belfagor2005/tvManager/actions/workflows/ruff.yml)

[![Visitors](https://komarev.com/ghpvc/?username=Belfagor2005&label=Repository%20Views&color=blueviolet)](https://github.com/Belfagor2005)
[![Donate](https://img.shields.io/badge/_-Donate-red.svg?logo=githubsponsors&labelColor=555555&style=for-the-badge)](https://ko-fi.com/lululla)
[![Donate](https://img.shields.io/badge/_-Donate-green.svg?logo=githubsponsors&labelColor=555555&style=for-the-badge)](https://paypal.me/belfagor2005)


<div align="center">

  ![tvManager Logo](https://github.com/Belfagor2005/tvManager/blob/main/usr/lib/enigma2/python/Plugins/Extensions/tvManager/logo.png)

**Enterprise Grade Enigma2 Softcam Management Plugin**
  
*Professional softcam management solution for Enigma2-based receivers*

</div>

## 📖 Overview

**tvManager** (Softcam Manager) is a comprehensive, enterprise-grade plugin designed for Enigma2 systems that provides complete control and management of softcams. With its professional interface and robust feature set, it simplifies softcam operations while offering advanced capabilities for power users.

## ✨ Key Features

### 🎮 Core Management
- **One-Click Control** - Start, stop, and restart softcams effortlessly
- **Multi-Cam Support** - OSCam, CCcam, NCam, MGcamd, GCam, Wicardd
- **Auto-Detection** - Running cams detected from the process list: "(Active)" only when the cam really runs
- **Quick Restart** - Instant softcam restart functionality
- **Reliable Autostart** - The selected cam is started at boot (`/etc/clist.list` + camscript)

### 📊 Monitoring & Information
- **Real-time ECM Info** - Readable summary (CAID, PID, provider, reader, hops, ECM time); multi-tuner `ecm*.info`
- **System Resources** - Memory, real CPU % and running/installed cams
- **Process Detection** - Intelligent cam process identification
- **Resource Statistics** - Comprehensive system usage metrics

### 💾 Backup & Configuration
- **Automated Backups** - Timestamped backups in `/etc/tvManager/backup` (kept across reboots, last 10)
- **Restore System** - Restores every saved file to its original path
- **Running Cam Config** - Also saves `oscam/ncam .conf .user .dvbapi` from the running cam's config dir
- **Config Management** - Centralized control of all cam configurations

### 🔧 Integrated Tools
- **OSCam / NCam Status** - One table with server, readers and clients, live log, memory bar,
  start/stop/restart (works whoever started the cam, JSON or XML webif API)
- **CCcam Info** - Self-contained: works on OpenPLi/DreamOS too (no image setup.xml or keymap needed)
- **Download Manager** - Integrated softcam downloader with repository support
- **System Cleanup** - Temporary file and cache management
- **Tivusat Reader Keys** - Manages only its own `Tivusat-183E` reader, never your own readers

### 🎯 Smart Features
- **Quick Shortcuts** - Number key shortcuts for fast access (0-9)
- **Multi-Skin Support** - HD, FHD, UHD compatibility
- **Cross-Platform** - DreamOS, OpenPLi, OpenATV support
- **Background Operations** - Network calls in background threads, the GUI never freezes
- **Update Check** - When the home screen opens (at most once a day) the plugin checks GitHub in the
  background and offers the new version; nothing is installed without your OK. INFO key = manual check

## 🚀 Quick Start

### Installation
```bash
# Automatic installation via plugin menu
# Or manual installation from releases
```

### Basic Usage
1. **Navigate** to Softcam Manager in your Enigma2 menu
2. **Select** your desired softcam from the list
3. **Start/Stop** using color buttons (Green/Red)
4. **Access Info** with Blue button for active cam details

### Quick Shortcuts
| Key | Function | Key | Function |
|-----|----------|-----|----------|
| **0** | Update Softcam Keys | **5** | Restore Backup |
| **1** | CCcam Info | **6** | System Cleanup |
| **2** | OSCam Info | **7** | Update Tivusat reader keys |
| **3** | NCam Info | **8** | Help Menu |
| **4** | Create Backup | **9** | Restart GUI |

### OSCam / NCam Info keys
| Key | Function |
|-----|----------|
| **Red** | Stop cam |
| **Green** | Start / Restart cam |
| **Yellow** | Capabilities of the cam build |
| **Blue** | Full screen live log |
| **OK** | Entitlements of the selected reader |
| **Menu** | ECM info, reader statistics, manual webif setup |

## 🛠 Technical Specifications

### Supported Architectures
- ARM, AArch64, MIPS, Cortex, SH4
- Multi-platform compatibility

### Python Compatibility
- Python 3.x (tested)
- Python 2.7.x (code kept compatible, not tested)

### Image Compatibility
- OpenPLi
- OpenATV  
- DreamOS
- Most Enigma2 distributions

### Configuration Files Managed
- `/etc/CCcam.cfg`
- `/etc/tuxbox/config/oscam.server`
- `/etc/tuxbox/config/ncam.server`
- `/usr/keys/SoftCam.Key`
- `/etc/clist.list` (active cam) and `/etc/startcam.sh` (cam started at boot)
- Backups: `/etc/tvManager/backup/backup_YYYYMMDD_HHMMSS/`

## 📁 Project Structure

```
tvManager/
├── data/                 # Core functionality modules
│   ├── Utils.py         # Small helpers (user agent, base64, download)
│   ├── camwebif.py      # Finds the running OSCam/NCam and talks to its webif
│   ├── camscripts.py    # Reads /usr/camscript (cam id = script file name)
│   ├── OScamStatus.py   # OSCam / NCam status screen
│   ├── GetEcmInfo.py    # ECM information handling
│   ├── Console.py       # System command execution
│   └── *Info.py         # Cam-specific information panels
├── res/skins/           # Multi-resolution skin support
│   ├── hd/              # HD skins (1280x720)
│   ├── fhd/             # Full HD skins (1920x1080)
│   └── uhd/             # Ultra HD skins (2560x1440)
└── logos/               # Application images and icons
```

## 📝 Changelog

### 3.7 (2026-11-22)
**Fixes**
- `data/camscripts.py`, `data/camwebif.py` and `data/OScamStatus.py` were missing from 3.6
  (the plugin did not open and the cam was not started at boot)
- `.gitignore`: `lib/` excluded every new file under `usr/lib/`, `*.mo` the new translations
- `installer.sh` checks the downloaded archive and stops if a plugin file is missing (installed version kept)

### 3.6 (2026-11-21)
**New**
- Update check when the home screen opens: at most once a day, in background, asks before installing
  (default No). INFO key = manual check as before

**Fixes**
- Cams are identified by the script file name (`/usr/camscript/<name>.sh`); the `OSD=` name is only the label, so a cam starts even when the two differ. Only `*.sh` files are listed; an old `clist.list` holding the OSD name is converted automatically
- ipk/deb package scripts rewritten:
  - an upgrade no longer deletes `/etc/clist.list` and `/etc/startcam.sh` (the selected cam is kept)
  - no `opkg update`/`opkg install` inside the scripts (the package manager is locked while they run)
  - no network download during installation, no files deleted in `/tmp`
  - no changes to system libraries (libssl/libcrypto links) and no removal of other packages
  - cam config backups kept on remove, deleted only on purge
- OScamInfo/NcamInfo no longer need python `six`

### 3.5 (2026-11-20)
**Security**
- Plugin update and cam downloads verify TLS certificates; installer is downloaded first, then run
- Download URLs and file names are quoted (no shell injection); install only if the download succeeded
- Removed the global `ssl` patch that disabled certificate checks for every plugin in enigma2
- Config files written with permissions 644
- `update_oscam_codes.sh` and `emm_sender.sh` rewritten for busybox `sh`; they no longer touch other files

**Fixes**
- Backup/restore: backups were written to one folder and searched in another; now `/etc/tvManager/backup`
- Quick restart crash (translation function `_` was overwritten)
- `/etc/clist.list` no longer contains "None"; `/etc/startcam.sh` always starts the cam (never `cam_down`)
- No more `opkg update` at every boot and no `/tmp` cleanup at every opening
- ECM info no longer freezes after opening a sub screen
- Local XML (green key), `.tar.bz2` packages, numeric version compare (3.10 > 3.4)
- OSCam/NCam Info: connects to 127.0.0.1, passwords with "=", HTTPS port "+", readable errors
- Own config sections (`config.tvm_oscaminfo`, `config.tvm_cccaminfo`): the image's OScamInfo/CCcamInfo
  settings are no longer overwritten. Manual settings of the plugin info screens must be entered again once.
- CCcamInfo: remote box crash, "Local box" deleting the profiles path, Share View keys, Organizer, PrioMaker autostart
- `Utils.py` reduced to what the plugin uses (faster start)

**New**
- OSCam / NCam status screen (OpenATV style, standalone)
- Home screen: real CPU %, running/installed cams, "(Active)" only when the cam runs, smart color keys

## 🔧 Advanced Features

### Resource Monitoring
```python
# Real-time system monitoring
- Memory usage tracking
- CPU load analysis  
- Active process detection
- Performance optimization
```

### Backup System
```python
# Automated backup management
- Configuration snapshots
- Timestamped versions
- Selective restoration
- Integrity verification
```

### Error Handling
```python
# Enterprise-grade error management
- Safe command execution
- Retry logic implementation
- Graceful failure recovery
- Comprehensive logging
```

## 🤝 Contributing

We welcome contributions from the community! 

### Development Areas
- New softcam support
- Additional skin development
- Feature enhancements
- Bug fixes and optimization
- Documentation improvements

### Reporting Issues
Please use the GitHub Issues section to report bugs or request features, including:
- Detailed description of the issue
- Steps to reproduce
- System information
- Relevant log files

## 📄 License

This project is licensed under the **GNU General Public License v3.0** - see the [LICENSE](LICENSE) file for details.

## ⚠️ Disclaimer

**Important Legal Notice:**

This plugin is a manager for softcam software installed on your receiver. It does not contain keys,
subscriptions or card data. Use it only with smart cards and subscriptions you are entitled to,
in accordance with the laws of your country and the terms of your provider.

## 👥 Credits

### Core Development
- **Lululla** - Lead Developer & Architecture
- **MMark** - Skin Design & UI/UX

### Special Thanks
- Open Source Community
- Beta Testers
- Feature Contributors

## 📞 Support

- **Repository**: [GitHub/Belfagor2005/tvManager](https://github.com/Belfagor2005/tvManager)
- **Issues**: [GitHub Issues](https://github.com/Belfagor2005/tvManager/issues)
- **Discussions**: Community forums and Enigma2 groups

---

<div align="center">

**⭐ Star this repository if you find it helpful!**

*Professional Softcam Management for Enigma2 Systems*

</div>
