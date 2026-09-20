#!/bin/sh
# Print the tested versions, then run pytest (extra arguments are passed through).
python - <<'PY'
import sys

import homeassistant.const as const

print(f"Python {sys.version.split()[0]} / Home Assistant {const.__version__}", flush=True)
PY
exec python -m pytest -p no:cacheprovider "$@"
