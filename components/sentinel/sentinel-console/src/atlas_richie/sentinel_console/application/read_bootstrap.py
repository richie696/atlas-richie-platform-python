"""Application use case for the public, request-aware bootstrap snapshot."""

from __future__ import annotations

from ..domain.bootstrap import BootstrapSnapshot, InitializedBootstrap, OpenSetupBootstrap
from .errors import BootstrapAuthorityUnavailable
from .bootstrap_ports import (
    BootstrapInitializationReader,
    BootstrapOperatorSessionVerifier,
    SetupWindowReader,
)


class ReadBootstrap:
    """Compose durable setup facts with this request's operator grant."""

    def __init__(
        self,
        initialization_reader: BootstrapInitializationReader,
        setup_window_reader: SetupWindowReader,
        operator_verifier: BootstrapOperatorSessionVerifier,
    ) -> None:
        self._initialization_reader = initialization_reader
        self._setup_window_reader = setup_window_reader
        self._operator_verifier = operator_verifier

    async def execute(self, opaque_operator_session: str | None) -> BootstrapSnapshot:
        """Read once; a dependency failure is never reinterpreted as uninitialized."""
        initialized = await self._initialization_reader.is_initialized()
        if type(initialized) is not bool:
            raise BootstrapAuthorityUnavailable(
                "bootstrap initialization authority returned an invalid fact"
            )
        if initialized:
            return InitializedBootstrap()

        setup_available = await self._setup_window_reader.is_setup_window_open()
        if type(setup_available) is not bool:
            raise BootstrapAuthorityUnavailable(
                "bootstrap setup-window authority returned an invalid fact"
            )
        operator_authorized = False
        if setup_available:
            verified = await self._operator_verifier.is_current_operator(
                opaque_operator_session
            )
            if type(verified) is not bool:
                raise BootstrapAuthorityUnavailable(
                    "bootstrap session authority returned an invalid fact"
                )
            operator_authorized = verified
        return OpenSetupBootstrap(
            setup_available=setup_available,
            operator_authorized=operator_authorized,
        )
