#!/bin/bash
# Service macOS qui réapplique le profil Kiyo à chaque branchement.
#   ./service.sh installer [profil]   (profil « perso » par défaut)
#   ./service.sh retirer
#   ./service.sh etat
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
LABEL=com.kiyoctl.watch
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/kiyoctl.log"
case "$1" in
  installer)
    PROFIL="${2:-perso}"
    mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
    cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$DIR/.venv/bin/python</string>
    <string>-u</string>
    <string>$DIR/kiyoctl.py</string>
    <string>watch</string>
    <string>$PROFIL</string>
  </array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>ProcessType</key><string>Background</string>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
PL
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$PLIST"
    echo "Service installé (profil « $PROFIL »). Journal : $LOG"
    ;;
  retirer)
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"
    echo "Service retiré."
    ;;
  etat)
    launchctl print "gui/$(id -u)/$LABEL" 2>/dev/null | grep -E "state|pid" | head -3 || echo "Service non installé."
    tail -5 "$LOG" 2>/dev/null || true
    ;;
  *) echo "usage: $0 installer [profil] | retirer | etat"; exit 1 ;;
esac
