import os
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

# Tests never touch real data, never use real keys, and never call a real model.
_TMP = Path(tempfile.mkdtemp(prefix="ocra_test_"))
os.environ["APP_MODE"] = "demo"
os.environ["DATABASE_PATH"] = str(_TMP / "test_demo.db")
os.environ["RESEARCH_CACHE_PATH"] = str(_TMP / "cache.db")
os.environ["PYDANTIC_AI_NO_BANNER"] = "1"
os.environ["ENABLE_SCHEDULER"] = "false"
