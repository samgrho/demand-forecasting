"""PyInstaller entry script (a plain script, so the app package keeps its imports)."""

import sys

from app.desktop import main

sys.exit(main())
