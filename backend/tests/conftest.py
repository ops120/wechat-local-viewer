"""Test path setup: make `backend/` importable as the `app` package root."""

import pathlib
import sys

BACKEND_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
