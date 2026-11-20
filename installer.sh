#!/bin/sh
# tvManager installer - runs with busybox sh (the plugin starts it with /bin/sh)

version='3.5'
changelog='\nSecurity: TLS checks, safe downloads, no global SSL patch\nNew OSCam/NCam status screen\nBackup/restore fixed (/etc/tvManager/backup)\nCCcamInfo works outside OpenATV\nMany fixes (see README)'

TMPPATH=/tmp/tvManager-install
FILEPATH=/tmp/tvManager-main.tar.gz
URL='https://github.com/Belfagor2005/tvManager/archive/refs/heads/main.tar.gz'

echo "Starting tvManager installation..."

if [ ! -d /usr/lib64 ]; then
    PLUGINPATH=/usr/lib/enigma2/python/Plugins/Extensions/tvManager
else
    PLUGINPATH=/usr/lib64/enigma2/python/Plugins/Extensions/tvManager
fi

cleanup() {
    [ -d "$TMPPATH" ] && rm -rf "$TMPPATH"
    [ -f "$FILEPATH" ] && rm -f "$FILEPATH"
    [ -d "/tmp/tvManager-main" ] && rm -rf "/tmp/tvManager-main"
}

detect_os() {
    if [ -f /var/lib/dpkg/status ]; then
        OSTYPE="DreamOs"
        STATUS="/var/lib/dpkg/status"
    elif [ -f /etc/opkg/opkg.conf ] || [ -f /var/lib/opkg/status ]; then
        OSTYPE="OE"
        STATUS="/var/lib/opkg/status"
    else
        OSTYPE="Unknown"
        STATUS=""
    fi
    echo "Detected OS type: $OSTYPE"
}

UPDATED=0
pkg_update() {
    [ "$UPDATED" = 1 ] && return 0
    UPDATED=1
    case "$OSTYPE" in
        DreamOs) apt-get update >/dev/null 2>&1 ;;
        OE) opkg update >/dev/null 2>&1 ;;
    esac
}

install_pkg() {
    pkg=$1
    if [ -n "$STATUS" ] && grep -qs "^Package: $pkg\$" "$STATUS"; then
        echo "$pkg already installed"
        return 0
    fi
    echo "Installing $pkg..."
    pkg_update
    case "$OSTYPE" in
        DreamOs) apt-get install -y "$pkg" >/dev/null 2>&1 ;;
        OE) opkg install "$pkg" >/dev/null 2>&1 ;;
        *) false ;;
    esac || echo "Could not install $pkg, continuing anyway..."
}

detect_os
cleanup
mkdir -p "$TMPPATH"

command -v wget >/dev/null 2>&1 || install_pkg wget
if ! command -v wget >/dev/null 2>&1; then
    echo "wget is missing and could not be installed."
    exit 1
fi

# Python 3 images often have only "python3"
if command -v python3 >/dev/null 2>&1 || python --version 2>&1 | grep -q '^Python 3\.'; then
    echo "Python3 image detected"
    install_pkg python3-requests
    install_pkg python3-six
else
    echo "Python2 image detected"
    install_pkg python-requests
    install_pkg python-six
fi
# root certificates: downloads are now verified
install_pkg ca-certificates

echo "Downloading tvManager..."
if ! wget -q "$URL" -O "$FILEPATH"; then
    echo "Failed to download tvManager package!"
    echo "If this is a certificate error: opkg install ca-certificates (or check date/time of the box)"
    cleanup
    exit 1
fi

echo "Extracting package..."
if ! tar -xzf "$FILEPATH" -C "$TMPPATH"; then
    echo "Failed to extract tvManager package!"
    cleanup
    exit 1
fi

SRC=""
for d in "$TMPPATH/tvManager-main/usr/lib/enigma2/python/Plugins/Extensions/tvManager" \
         "$TMPPATH/tvManager-main/usr/lib64/enigma2/python/Plugins/Extensions/tvManager"; do
    [ -d "$d" ] && { SRC="$d"; break; }
done
if [ -z "$SRC" ]; then
    echo "Could not find plugin files in extracted archive"
    find "$TMPPATH" -type d | head -10
    cleanup
    exit 1
fi

echo "Installing plugin files..."
mkdir -p "$PLUGINPATH"
cp -r "$SRC"/* "$PLUGINPATH/"
# old compiled files would keep running the previous code
find "$PLUGINPATH" -name "*.pyc" -delete 2>/dev/null
find "$PLUGINPATH" -name "*.pyo" -delete 2>/dev/null
find "$PLUGINPATH" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null
chmod 755 "$PLUGINPATH"/data/*.sh "$PLUGINPATH"/auto "$PLUGINPATH"/auto2 2>/dev/null
sync

if [ -z "$(ls -A "$PLUGINPATH" 2>/dev/null)" ]; then
    echo "Plugin installation failed or directory is empty!"
    cleanup
    exit 1
fi

cleanup
sync

box_type=$(sed -n '1p' /etc/hostname 2>/dev/null)
distro_value="Unknown"
distro_version="Unknown"
if [ -r /etc/os-release ]; then
    distro_value=$(grep '^NAME=' /etc/os-release 2>/dev/null | cut -d'"' -f2)
    distro_version=$(grep '^VERSION_ID=' /etc/os-release 2>/dev/null | cut -d'"' -f2)
elif [ -r /etc/issue ]; then
    distro_value=$(head -n 1 /etc/issue 2>/dev/null | awk '{print $1}')
    distro_version=$(head -n 1 /etc/issue 2>/dev/null | awk '{print $2}')
fi
python_vers=$( (python3 --version || python --version) 2>&1 | head -n1)

cat <<EOF

#########################################################
#       tvManager $version INSTALLED SUCCESSFULLY           #
#                developed by LULULLA                   #
#               https://corvoboys.org                   #
#########################################################
#        Restart the GUI to load the new version        #
#########################################################
^^^^^^^^^^Debug information:
BOX MODEL: ${box_type:-Unknown}
OS SYSTEM: $OSTYPE
PYTHON: $python_vers
IMAGE NAME: ${distro_value:-Unknown}
IMAGE VERSION: ${distro_version:-Unknown}
PLUGIN PATH: $PLUGINPATH
PLUGIN VERSION: $version
EOF
printf 'CHANGELOG: %b\n' "$changelog"

exit 0
