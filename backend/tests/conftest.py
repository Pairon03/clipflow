import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

# pasta de dados isolada para toda a sessão de testes
_DATA = Path(tempfile.mkdtemp(prefix="clipflow-test-"))
os.environ["CLIPFLOW_DATA_DIR"] = str(_DATA / "data")
os.environ["CLIPFLOW_CONFIG"] = str(_DATA / "nao-existe.toml")

from app import config  # noqa: E402

config.reload()


@pytest.fixture(scope="session")
def media_dir() -> Path:
    d = _DATA / "media"
    d.mkdir(exist_ok=True)
    return d


@pytest.fixture(scope="session")
def sample_two(media_dir):
    from media import build_sample
    return build_sample(media_dir / "two", "two")


@pytest.fixture(scope="session")
def sample_moving(media_dir):
    from media import build_sample
    return build_sample(media_dir / "moving", "moving")


@pytest.fixture(scope="session")
def sample_none(media_dir):
    from media import build_sample
    return build_sample(media_dir / "none", "none")
