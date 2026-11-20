#!/bin/sh
# DESCRIPTION=send emm
# Sends the published EMMs for Tivusat (CAID 183E) to your own Tivusat card
# through the OSCam webif. mod by lululla - rewritten for busybox sh (tvManager)
#
# Output goes to the screen (tvManager Console) and to /tmp/tvmanager_emm.log

ATR_183E='3F FF 95 00 FF 91 81 71 FE 47 00 54 49 47 45 52 36 30 31 20 52 65 76 4D 38 37 14'
EMM_URL_B64='aHR0cHM6Ly9wYXN0ZWJpbi5jb20vcmF3L1U0ZU02RGpW'
EMM_URL2_B64='aHR0cHM6Ly9wYXN0ZWJpbi5jb20vcmF3L2FWaVJ3TjVy'
EMM_PREFIX='82708E0000000000D3875411'
IP='127.0.0.1'
CAID='183E'
LOG=/tmp/tvmanager_emm.log

WORK=$(mktemp -d /tmp/tvm_emm.XXXXXX) || exit 1
trap 'rm -rf "$WORK"' EXIT

say() { echo "$1"; echo "$(date '+%H:%M:%S') $1" >> "$LOG"; }
: > "$LOG"

# ---- find the running OSCam config ------------------------------------
VERSION_FILE=""
for v in /tmp/.oscam/oscam.version /tmp/.*/oscam.version; do
    [ -f "$v" ] && { VERSION_FILE="$v"; break; }
done
if [ -z "$VERSION_FILE" ]; then
    say "Error: OSCam is not running (oscam.version not found)."
    exit 1
fi
CONF_DIR=$(sed -n 's/^ConfigDir:[[:space:]]*//p' "$VERSION_FILE" | head -n1)
CONF_DIR=${CONF_DIR%/}
OSCAM_CONF="$CONF_DIR/oscam.conf"
LOCAL_EMM_FILE="$CONF_DIR/emm"
if [ ! -f "$OSCAM_CONF" ]; then
    say "Error: $OSCAM_CONF not found."
    exit 1
fi

# read one key from the [webif] section, ignoring comments
webif_value() {
    awk -v key="$1" '
        /^[[:space:]]*[#;]/ { next }
        /^[[:space:]]*\[/ { sec = tolower($0); next }
        sec ~ /\[webif\]/ {
            line = $0; k = line; sub(/=.*/, "", k); gsub(/[[:space:]]/, "", k)
            if (tolower(k) == key) { sub(/^[^=]*=[[:space:]]*/, "", line); sub(/[[:space:]]+$/, "", line); print line; exit }
        }' "$OSCAM_CONF"
}
OSCAM_USER=$(webif_value httpuser)
OSCAM_PASSWD=$(webif_value httppwd)
OSCAM_HTTPPORT=$(webif_value httpport)
case "$OSCAM_HTTPPORT" in
    +*) PROTOCOL=https ;;
    *)  PROTOCOL=http ;;
esac
PORT=$(echo "$OSCAM_HTTPPORT" | tr -d '+ ')
if [ -z "$PORT" ] || [ "$PORT" = "0" ]; then
    say "Error: OSCam webif disabled (httpport) in $OSCAM_CONF"
    exit 1
fi
BASE="$PROTOCOL://$IP:$PORT"

# ---- curl ---------------------------------------------------------------
if ! command -v curl >/dev/null 2>&1; then
    say "curl not found, installing..."
    if command -v opkg >/dev/null 2>&1; then
        opkg update >/dev/null 2>&1; opkg install curl >/dev/null 2>&1
    elif command -v apt-get >/dev/null 2>&1; then
        apt-get update >/dev/null 2>&1; apt-get install -y curl >/dev/null 2>&1
    fi
    command -v curl >/dev/null 2>&1 || { say "Error: curl installation failed."; exit 1; }
fi
# -k only for the local OSCam webif (self-signed certificate)
webif() { curl -s -k --max-time 10 --anyauth --user "$OSCAM_USER:$OSCAM_PASSWD" "$BASE/$1"; }

# ---- download EMM list --------------------------------------------------
say "Downloading EMM list..."
REMOTE="$WORK/emm.remote"
for b64 in "$EMM_URL_B64" "$EMM_URL2_B64"; do
    url=$(echo "$b64" | base64 -d 2>/dev/null)
    curl -s --max-time 20 "$url" | tr -d '\r' > "$REMOTE"
    grep -q "^$EMM_PREFIX" "$REMOTE" && break
done
if ! grep -q "^$EMM_PREFIX" "$REMOTE"; then
    say "Error: no valid EMM downloaded (both sources failed)."
    exit 1
fi
if [ ! -f "$LOCAL_EMM_FILE" ] || ! cmp -s "$REMOTE" "$LOCAL_EMM_FILE"; then
    cat "$REMOTE" > "$LOCAL_EMM_FILE"
    say "EMM list updated: $LOCAL_EMM_FILE"
fi

# ---- active readers -----------------------------------------------------
webif "status.html" | grep "Restart Reader" \
    | sed -e 's|.*status.html?action=restart&amp;label=||' -e 's|".*||' > "$WORK/readers"
if [ ! -s "$WORK/readers" ]; then
    say "No active reader found (check httpuser/httppwd in $OSCAM_CONF)."
    exit 1
fi

ATR_CLEAN=$(echo "$ATR_183E" | tr -d '[:space:]')
SENT_TOTAL=0
while IFS= read -r label; do
    [ -n "$label" ] || continue
    atr=$(webif "entitlements.html?label=$label" \
        | sed -n 's/.*<TD COLSPAN="4">\(.*\)<\/TD>.*/\1/p' | head -n1 | tr -d '[:space:]')
    case "$atr" in
        "$ATR_CLEAN"*) ;;
        *) continue ;;
    esac
    say "Tivusat card found on reader '$label', sending EMM..."
    sent=0
    while IFS= read -r EMM; do
        EMM=$(echo "$EMM" | tr -d ' \t')
        case "$EMM" in
            "$EMM_PREFIX"*)
                webif "emm_running.html?label=$label&emmcaid=$CAID&ep=$EMM&action=Launch" >/dev/null
                sent=$((sent + 1))
                say "  EMM $sent sent: $(echo "$EMM" | cut -c1-20)..."
                sleep 1
                ;;
        esac
    done < "$LOCAL_EMM_FILE"
    SENT_TOTAL=$((SENT_TOTAL + sent))
    curl -s --max-time 5 "http://$IP/web/message?text=EMM+sent+to+$label+($sent)&type=2&timeout=5" >/dev/null
done < "$WORK/readers"

if [ "$SENT_TOTAL" -eq 0 ]; then
    say "No Tivusat card (ATR 183E) found on the active readers."
    exit 1
fi
say "Done: $SENT_TOTAL EMM sent."
exit 0
