import os
import sys
from unittest.mock import MagicMock

# Inject any missing environment variables required at module import time
os.environ.setdefault("TEST_NAMESPACE", "dummy-namespace")

# Ensure repository root is in sys.path so 'tests.service_catalog...' imports succeed during collection
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

# Stub out native GUI/desktop libraries so pytest collection succeeds headlessly
class DummyModule(MagicMock):
    def __getattr__(self, name):
        return MagicMock()

# Inject dogtail stubs into sys.modules
sys.modules["dogtail"] = DummyModule()
sys.modules["dogtail.rawinput"] = DummyModule()
sys.modules["dogtail.tree"] = DummyModule()
sys.modules["dogtail.utils"] = DummyModule()

