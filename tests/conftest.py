import atexit
import os
import shutil
import tempfile

# store opens its SQLite file at import time, so point it at a throwaway folder before any test imports it.
_data = tempfile.mkdtemp(prefix="chade-test-")
os.environ["DATA_DIR"] = _data
atexit.register(shutil.rmtree, _data, ignore_errors=True)
