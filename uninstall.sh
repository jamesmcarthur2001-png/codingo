#!/usr/bin/env bash
# Removes exactly what install.sh added to ~/.claude: the files in its manifest and its hook entries.
# Files install.sh backed up are put back.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="$HOME/.claude"
WORKFLOW_DIR="$CLAUDE_DIR/midnight-workflow"
MANIFEST="$WORKFLOW_DIR/installed-files.txt"
BACKUP_DIR="$WORKFLOW_DIR/backup"

if [ ! -f "$MANIFEST" ]; then
    echo "midnight-workflow is not installed in $CLAUDE_DIR (no $MANIFEST)."
    python3 "$REPO_DIR/install/merge_settings.py" remove "$CLAUDE_DIR/settings.json"
    exit 0
fi

while IFS= read -r installed_file; do
    if [ -z "$installed_file" ]; then
        continue
    fi
    rm -f "$CLAUDE_DIR/$installed_file"
    if [ -e "$BACKUP_DIR/$installed_file" ]; then
        mkdir -p "$(dirname "$CLAUDE_DIR/$installed_file")"
        mv "$BACKUP_DIR/$installed_file" "$CLAUDE_DIR/$installed_file"
        echo "Restored your $CLAUDE_DIR/$installed_file"
    fi
    directory="$(dirname "$CLAUDE_DIR/$installed_file")"
    while [ "$directory" != "$CLAUDE_DIR" ] && rmdir "$directory" 2>/dev/null; do
        directory="$(dirname "$directory")"
    done
done < "$MANIFEST"

rm -rf "$WORKFLOW_DIR"
python3 "$REPO_DIR/install/merge_settings.py" remove "$CLAUDE_DIR/settings.json"
echo "midnight-workflow removed from $CLAUDE_DIR."
