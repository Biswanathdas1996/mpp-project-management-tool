import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

_tmp = tempfile.mkdtemp(prefix="pma-test-")
os.environ.setdefault("PMA_DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ.setdefault("PMA_STORAGE_LOCAL_PATH", f"{_tmp}/storage")
os.environ.setdefault("PMA_BOOTSTRAP_ADMIN_EMAIL", "admin@test.local")
os.environ.setdefault("PMA_BOOTSTRAP_ADMIN_PASSWORD", "AdminPass123")
os.environ.setdefault("PMA_ENV", "test")
os.environ.setdefault("PMA_QUEUE_BACKEND", "inline")
os.environ.setdefault("PMA_AI_DEFAULT_MODE", "off")
# The main e2e flow exercises the manual mapping wizard; test_auto_mapping.py turns automatic approval on.
os.environ.setdefault("PMA_MAPPING_AUTO_APPROVE", "off")

BACKEND = Path(__file__).resolve().parents[1]

# TestClient runs the app lifespan on a portal thread; start the JVM here on the main thread
# (as uvicorn / the RQ worker do) so the process can shut down cleanly.
from app.parser.mpp_parser import mpxj_classes  # noqa: E402

mpxj_classes()
SAMPLES = Path(_tmp) / "samples"


@pytest.fixture(scope="session")
def sample_files() -> list[Path]:
    subprocess.run([sys.executable, str(BACKEND / "scripts" / "generate_sample_plans.py"), str(SAMPLES)],
                   check=True, cwd=BACKEND, capture_output=True)
    return sorted(SAMPLES.glob("*.xml"))


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def admin_headers(client):
    r = client.post("/api/auth/login", json={"email": "admin@test.local", "password": "AdminPass123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def wait_for(client, headers, snapshot_id, statuses, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        s = client.get(f"/api/snapshots/{snapshot_id}", headers=headers).json()
        if s["status"] in statuses:
            return s
        time.sleep(0.3)
    raise AssertionError(f"snapshot {snapshot_id} stuck in {s['status']}")
