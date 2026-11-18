"""S3 endpoint gate so adapter tests skip cleanly without a backend."""

from __future__ import annotations

import os

import pytest

from atlas_richie.testing.pytest_support import skip_unless_reachable

S3_URL = os.environ.get("ATLAS_RICHIE_STORAGE_S3_URL", "http://127.0.0.1:9100")
ACCESS_KEY = os.environ.get("ATLAS_RICHIE_STORAGE_S3_ACCESS_KEY", "minioadmin")
SECRET_KEY = os.environ.get("ATLAS_RICHIE_STORAGE_S3_SECRET_KEY", "minioadmin")


@pytest.fixture(scope="session")
def s3_url() -> str:
    return S3_URL


@pytest.fixture(scope="session")
def requires_s3(s3_url: str) -> None:
    skip_unless_reachable(s3_url, "S3 endpoint", default_port=9000, env_hint="ATLAS_RICHIE_STORAGE_S3_URL")


@pytest.fixture
def engine(requires_s3: None, s3_url: str):
    from atlas_richie.storage_s3 import S3StorageEngine

    return S3StorageEngine(
        endpoint_url=s3_url,
        aws_access_key_id=ACCESS_KEY,
        aws_secret_access_key=SECRET_KEY,
        force_path_style=True,
        region_name="us-east-1",
    )
