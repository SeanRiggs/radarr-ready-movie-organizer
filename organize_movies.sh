#!/bin/sh
# Keep this entry point beside organize_movies.py. Preview is the default.
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$SCRIPT_DIR/organize_movies.py" "$@"
