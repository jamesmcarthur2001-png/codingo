#!/usr/bin/env bash
# Installs midnight-workflow at user level into ~/.claude (Ubuntu). Safe to run again: it updates the files
# and replaces its own hook entries. Files it would overwrite that it didn't install are backed up first,
# and uninstall.sh puts them back.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="$HOME/.claude"
WORKFLOW_DIR="$CLAUDE_DIR/midnight-workflow"
MANIFEST="$WORKFLOW_DIR/installed-files.txt"
BACKUP_DIR="$WORKFLOW_DIR/backup"
COMMANDS=(feature.md map-services.md map-library.md)
AGENTS=(explorer.md doc-auditor.md skill-mapper.md conventions-reviewer.md playwright-reviewer.md)

if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
    echo "midnight-workflow needs python3 3.10 or newer." >&2
    exit 1
fi

mkdir -p "$WORKFLOW_DIR" "$BACKUP_DIR"
OLD_MANIFEST="$(mktemp)"
NEW_MANIFEST="$(mktemp)"
trap 'rm -f "$OLD_MANIFEST" "$NEW_MANIFEST"' EXIT
if [ -f "$MANIFEST" ]; then
    cp "$MANIFEST" "$OLD_MANIFEST"
fi

install_file() {
    local source="$1"
    local relative_target="$2"
    local target="$CLAUDE_DIR/$relative_target"
    if [ -e "$target" ] && ! grep -qxF "$relative_target" "$OLD_MANIFEST" && [ ! -e "$BACKUP_DIR/$relative_target" ]; then
        mkdir -p "$(dirname "$BACKUP_DIR/$relative_target")"
        cp -p "$target" "$BACKUP_DIR/$relative_target"
        echo "Backed up your $target"
    fi
    mkdir -p "$(dirname "$target")"
    cp "$source" "$target"
    echo "$relative_target" >> "$NEW_MANIFEST"
}

for command_file in "${COMMANDS[@]}"; do
    install_file "$REPO_DIR/commands/$command_file" "commands/$command_file"
done
for agent_file in "${AGENTS[@]}"; do
    install_file "$REPO_DIR/agents/$agent_file" "agents/$agent_file"
done
while IFS= read -r -d '' skill_file; do
    install_file "$skill_file" "skills/${skill_file#"$REPO_DIR/skills/"}"
done < <(find "$REPO_DIR/skills" -type f ! -path '*/__pycache__/*' -print0)
while IFS= read -r -d '' script_file; do
    relative_script="${script_file#"$REPO_DIR/scripts/"}"
    install_file "$script_file" "midnight-workflow/scripts/$relative_script"
    chmod +x "$CLAUDE_DIR/midnight-workflow/scripts/$relative_script"
done < <(find "$REPO_DIR/scripts" -type f -name '*.py' ! -path '*/__pycache__/*' -print0)

while IFS= read -r old_file; do
    if [ -n "$old_file" ] && ! grep -qxF "$old_file" "$NEW_MANIFEST"; then
        rm -f "$CLAUDE_DIR/$old_file"
        echo "Removed $CLAUDE_DIR/$old_file (no longer part of the workflow)"
    fi
done < "$OLD_MANIFEST"

sort -u "$NEW_MANIFEST" > "$MANIFEST"
python3 "$REPO_DIR/install/merge_settings.py" add "$CLAUDE_DIR/settings.json" "$REPO_DIR/settings/hooks.json"
echo "midnight-workflow installed into $CLAUDE_DIR ($(wc -l < "$MANIFEST") files). Restart Claude Code to load the hooks."
