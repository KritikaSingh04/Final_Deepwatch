#!/bin/sh
# DEEPWATCH launcher — creates the venv on first run, then serves the twin.
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
  ./.venv/bin/pip install -r requirements.txt
fi
[ -f data/dev_dataset.csv ] || ./.venv/bin/python -m simulator.generate
echo "DEEPWATCH → http://localhost:${PORT:-8010}"
exec ./.venv/bin/uvicorn server.app:app --port "${PORT:-8010}"
