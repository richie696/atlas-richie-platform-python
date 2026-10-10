"""Cross-store first-run setup ordering and recoverable completion handling."""

from __future__ import annotations

import hashlib
import hmac

from sqlalchemy.ext.asyncio import AsyncEngine

from ...application.bootstrap_initialization import (
    BootstrapInitializationForbidden,
    BootstrapInitializationInput,
    BootstrapInitializationOperationReader,
    BootstrapInitializationReceipt,
    BootstrapInitializationReason,
    BootstrapInitializationStatus,
    BootstrapInitializer,
)
from ...application.bootstrap_ports import (
    BootstrapInitializationLock,
    BootstrapOperatorSessionVerifier,
    BootstrapInitializationReader,
    SetupWindowController,
    SetupWindowReader,
)
from ...application.errors import BootstrapAuthorityUnavailable
from ...application.runtime_database_locator import RuntimeDatabaseLocatorStore
from ..bootstrap_database_engine import BootstrapDatabaseEngineFactory
from ..security.secret_cipher import AesGcmSecretCipher
from .bootstrap_initialization_reader import SqlAlchemyBootstrapInitializationReader
from .bootstrap_initialization_transaction import (
    SqlAlchemyBootstrapInitializationTransaction,
)
from .database_runtime import (
    ConsoleDatabaseConfiguration,
    create_database_engine_from_locator,
)
from .migration_runner import upgrade_database


class SqlAlchemyBootstrapInitializationCoordinator(
    BootstrapInitializer,
    BootstrapInitializationOperationReader,
    BootstrapInitializationReader,
):
    """Coordinate target migration, locator persistence, admin commit and close.

    Migration completes before the selected runtime locator is written. The
    locator is durable before the first-admin transaction, so a process restart
    can reconnect to the same pinned target. The target database guard is the
    completion authority; the external setup window is closed only after that
    guard commits and is also closed on the next bootstrap read if a process
    stopped between those two writes.
    """

    def __init__(
        self,
        *,
        database_engine_factory: BootstrapDatabaseEngineFactory,
        runtime_database_locator_store: RuntimeDatabaseLocatorStore,
        setup_window_reader: SetupWindowReader,
        setup_window_controller: SetupWindowController,
        operator_verifier: BootstrapOperatorSessionVerifier,
        initialization_lock: BootstrapInitializationLock,
        source_secret_cipher: AesGcmSecretCipher,
        idempotency_key: bytes,
    ) -> None:
        if not isinstance(source_secret_cipher, AesGcmSecretCipher):
            raise TypeError("registered-source secret cipher is required")
        if not isinstance(idempotency_key, bytes) or len(idempotency_key) < 32:
            raise ValueError("bootstrap idempotency key must be at least 32 bytes")
        self._database_engine_factory = database_engine_factory
        self._runtime_database_locator_store = runtime_database_locator_store
        self._setup_window_reader = setup_window_reader
        self._setup_window_controller = setup_window_controller
        self._operator_verifier = operator_verifier
        self._initialization_lock = initialization_lock
        self._source_secret_cipher = source_secret_cipher
        self._idempotency_key = bytes(idempotency_key)

    async def initialize(
        self,
        *,
        operator_session: str,
        request_key: str,
        input: BootstrapInitializationInput,
    ) -> BootstrapInitializationReceipt:
        """Run one serialized initialization attempt and release every engine."""
        async with self._initialization_lock.acquire():
            if not await self._operator_verifier.is_current_operator(
                operator_session
            ):
                raise BootstrapInitializationForbidden
            if not await self._setup_window_reader.is_setup_window_open():
                raise BootstrapInitializationForbidden

            engine = await self._open_selected_database(input)
            try:
                transaction = self._transaction(engine)
                receipt = await transaction.initialize(
                    operator_session=operator_session,
                    request_key=request_key,
                    input=input,
                )
                if receipt.status is BootstrapInitializationStatus.COMPLETED or (
                    receipt.status is BootstrapInitializationStatus.REJECTED
                    and receipt.reason is BootstrapInitializationReason.SETUP_CLOSED
                ):
                    await self._setup_window_controller.close_setup_window_if_open()
                return receipt
            finally:
                await engine.dispose()

    async def is_initialized(self) -> bool:
        """Read the target guard and finish a committed-but-not-closed setup."""
        async with self._initialization_lock.acquire():
            locator = await self._runtime_database_locator_store.read()
            if locator is None:
                return False
            engine = create_database_engine_from_locator(locator)
            try:
                initialized = await SqlAlchemyBootstrapInitializationReader(
                    engine
                ).is_initialized()
                if initialized:
                    await self._setup_window_controller.close_setup_window_if_open()
                return initialized
            finally:
                await engine.dispose()

    async def read(
        self, operator_session: str, request_key: str
    ) -> BootstrapInitializationReceipt | None:
        """Recover the original operator's receipt from the pinned target DB."""
        async with self._initialization_lock.acquire():
            locator = await self._runtime_database_locator_store.read()
            if locator is None:
                return None
            engine = create_database_engine_from_locator(locator)
            try:
                return await self._transaction(engine).read(
                    operator_session, request_key
                )
            finally:
                await engine.dispose()

    async def _open_selected_database(
        self, input: BootstrapInitializationInput
    ) -> AsyncEngine:
        locator = await self._runtime_database_locator_store.read()
        expected_url = ConsoleDatabaseConfiguration.from_bootstrap_candidate(
            input.database
        ).secret_url_for_storage()

        if (
            locator is not None
            and locator.target is not None
            and _same_secret(locator.database_url, expected_url)
        ):
            engine = create_database_engine_from_locator(locator)
            try:
                await upgrade_database(engine)
            except BaseException:
                await engine.dispose()
                raise
            return engine

        if locator is not None:
            previous_engine = create_database_engine_from_locator(locator)
            try:
                initialized = await SqlAlchemyBootstrapInitializationReader(
                    previous_engine
                ).is_initialized()
                if initialized:
                    await self._setup_window_controller.close_setup_window_if_open()
                    raise BootstrapInitializationForbidden
            finally:
                await previous_engine.dispose()

        prepared = await self._database_engine_factory.create(input.database)
        try:
            await upgrade_database(prepared.engine)
            await self._runtime_database_locator_store.write(
                prepared.locator_database_url,
                expected_revision=(locator.revision if locator is not None else None),
                target=prepared.locator_target,
            )
            return prepared.engine
        except BaseException:
            await prepared.engine.dispose()
            raise

    def _transaction(
        self, engine: AsyncEngine
    ) -> SqlAlchemyBootstrapInitializationTransaction:
        return SqlAlchemyBootstrapInitializationTransaction(
            engine,
            operator_verifier=self._operator_verifier,
            source_secret_cipher=self._source_secret_cipher,
            idempotency_key=self._idempotency_key,
        )


def _same_secret(first: str, second: str) -> bool:
    """Compare credential-bearing URLs without ordinary short-circuit equality."""
    return hmac.compare_digest(
        hashlib.sha256(first.encode("utf-8")).digest(),
        hashlib.sha256(second.encode("utf-8")).digest(),
    )


__all__ = ["SqlAlchemyBootstrapInitializationCoordinator"]
