"""Test fixtures for `atlas-richie-secret-gcp-kms`.

GCP has no local emulator for Secret Manager or KMS. Tests use
`unittest.mock.MagicMock` shaped like the real SDK clients.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest

from atlas_richie.secret.metadata import SecretBackend
from atlas_richie.secret_gcp_kms import (
    GcpSecretProperties,
    GcpSecretProviderFactory,
    GcpSecretClient,
)

REAL_GCP_PROJECT_ID = os.environ.get(
    "ATLAS_RICHIE_SECRET_GCP_TEST_PROJECT_ID",
)


@pytest.fixture
def gcp_sm_client_mock() -> MagicMock:
    return MagicMock()


@pytest.fixture
def gcp_kms_client_mock() -> MagicMock:
    return MagicMock()


@pytest.fixture
def gcp_session(
    gcp_sm_client_mock: MagicMock,
    gcp_kms_client_mock: MagicMock,
) -> Iterator[GcpSecretClient]:
    properties = GcpSecretProperties(project_id="test-project")
    provider_id = f"gcp-test-{uuid.uuid4().hex[:8]}"
    factory = GcpSecretProviderFactory(
        properties=properties,
        name=provider_id,
        client_factory=lambda _p: (gcp_sm_client_mock, gcp_kms_client_mock),
    )
    session = factory.create(factory.default_configuration())
    assert isinstance(session, GcpSecretClient)
    try:
        yield session
    finally:
        try:
            session.close()
        except Exception:  # noqa: BLE001
            pass


@pytest.fixture
def real_gcp_session() -> Iterator[GcpSecretClient]:
    if not REAL_GCP_PROJECT_ID:
        pytest.skip("ATLAS_RICHIE_SECRET_GCP_TEST_PROJECT_ID not set")
    properties = GcpSecretProperties(project_id=REAL_GCP_PROJECT_ID)
    factory = GcpSecretProviderFactory(properties=properties)
    session = factory.create(factory.default_configuration())
    try:
        yield session
    finally:
        try:
            session.close()
        except Exception:  # noqa: BLE001
            pass
