#!/bin/sh
# update-checker-uninstaller.sh - Removes update checker setup

SCRIPT_DIR="$HOME/.local/bin"
AUTOSTART_DIR="$HOME/.config/autostart"
SCRIPT_NAME="update-checker"

echo "Removing update checker..."

# Kill any running instances
if pgrep -f "$SCRIPT_DIR/$SCRIPT_NAME" >/dev/null 2>&1; then
    echo "Stopping running update checker processes..."
    pkill -f "$SCRIPT_DIR/$SCRIPT_NAME"
fi

# Remove the main script
if [ -f "$SCRIPT_DIR/$SCRIPT_NAME" ]; then
    rm "$SCRIPT_DIR/$SCRIPT_NAME"
    echo "Removed: $SCRIPT_DIR/$SCRIPT_NAME"
else
    echo "Script not found: $SCRIPT_DIR/$SCRIPT_NAME"
fi

# Remove the desktop entry
if [ -f "$AUTOSTART_DIR/update-checker.desktop" ]; then
    rm "$AUTOSTART_DIR/update-checker.desktop"
    echo "Removed: $AUTOSTART_DIR/update-checker.desktop"
else
    echo "Desktop entry not found: $AUTOSTART_DIR/update-checker.desktop"
fi

echo "Update checker removal complete!"