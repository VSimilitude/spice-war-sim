#!/bin/bash
set -e

cd "$(dirname "$0")/.."

mkdir -p web/python

python3 -c "
import zipfile, os
with zipfile.ZipFile('web/python/spice_war.zip', 'w', zipfile.ZIP_DEFLATED) as zf:
    for root, dirs, files in os.walk('src/spice_war'):
        dirs[:] = [d for d in dirs if d != '__pycache__']
        for f in files:
            if f.endswith('.pyc'):
                continue
            path = os.path.join(root, f)
            arcname = os.path.relpath(path, 'src')
            zf.write(path, arcname)
"

echo "Built web/python/spice_war.zip"
