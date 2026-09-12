"""Bootstrap 子系统单元测试: catalog + loader + post-processor。

中文
----
覆盖 binding catalog 加载、policy 应用、exposure 注入(env / file)。

English
--------
Bootstrap subsystem unit tests: catalog loading, policy application,
exposure injection (env / file).
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from atlas_richie.secret import (
    AtlasSecretEnvironmentPostProcessor,
    BootstrapSecretProperties,
    InMemorySecretProviderFactory,
    RequiredWhen,
    ResolverBackedBootstrapClient,
    SecretBinding,
    SecretBindingCatalog,
    SecretBindingCatalogLoader,
    SecretBindingCatalogSet,
    SecretBootstrapState,
    SecretExposure,
    SecretProviderConfiguration,
    SecretProviderDiscovery,
    SecretProviderTopology,
    SecretProviderType,
    SecretPropertyPolicy,
    SecretReference,
    SecretRegistry,
    SecretSnapshotManager,
)


def _config(name: str = "test") -> SecretProviderConfiguration:
    return SecretProviderConfiguration(name=name)


class CatalogLoaderTest(unittest.TestCase):
    def test_load_minimal(self) -> None:
        loader = SecretBindingCatalogLoader(
            {
                "name": "default",
                "bindings": [
                    {
                        "name": "db.password",
                        "provider": "vault",
                        "path": "db/password",
                    },
                ],
            },
        )
        catalog = loader.load()
        self.assertEqual(catalog.name, "default")
        self.assertEqual(len(catalog.bindings), 1)
        binding = catalog.bindings[0]
        self.assertEqual(binding.name, "db.password")
        self.assertEqual(binding.reference.provider, "vault")
        self.assertEqual(binding.exposure, SecretExposure.ENV)
        self.assertEqual(binding.required_when, RequiredWhen.STARTUP)

    def test_load_with_overrides(self) -> None:
        loader = SecretBindingCatalogLoader(
            {
                "name": "explicit",
                "bindings": [
                    {
                        "name": "tls.cert",
                        "provider": "vault",
                        "path": "tls/cert",
                        "kind": "tls_certificate",
                        "exposure": "file",
                        "required_when": "lazy",
                        "refresh": "file_rewrite",
                        "pattern": {"template": "TLS_${name}", "uppercase": False},
                    },
                ],
            },
        )
        catalog = loader.load()
        binding = catalog.bindings[0]
        self.assertEqual(binding.kind.value, "tls_certificate")
        self.assertEqual(binding.exposure, SecretExposure.FILE)
        self.assertEqual(binding.required_when, RequiredWhen.LAZY)
        self.assertEqual(binding.refresh.value, "file_rewrite")
        self.assertEqual(binding.property_name(), "TLS_tls.cert")

    def test_load_rejects_missing_required_fields(self) -> None:
        with self.assertRaises(ValueError):
            SecretBindingCatalogLoader(
                {
                    "name": "x",
                    "bindings": [
                        {"name": "no.provider", "path": "x"},
                    ],
                },
            ).load()


class CatalogSetTest(unittest.TestCase):
    def test_merged_last_wins(self) -> None:
        a = SecretBindingCatalog(
            name="a",
            bindings=(SecretBinding(
                name="k",
                reference=SecretReference(provider="v", path="a"),
            ),),
        )
        b = SecretBindingCatalog(
            name="b",
            bindings=(SecretBinding(
                name="k",
                reference=SecretReference(provider="v", path="b"),
            ),),
        )
        merged = SecretBindingCatalogSet(catalogs=(a, b)).merged()
        self.assertEqual(merged.bindings[0].reference.path, "b")


class PostProcessorTest(unittest.TestCase):
    def setUp(self) -> None:
        SecretRegistry.reset()
        self.registry = SecretRegistry.instance()
        self.factory = InMemorySecretProviderFactory(name="vault")
        self.session = self.factory.create(_config(name="vault"))
        self.registry.register("vault", self.session, factory=self.factory)
        # pre-seed a value
        self.session.writer.put(
            SecretReference(provider="vault", path="db/password"),
            b"sup3rs3cr3t",
        )
        self.binding = SecretBinding(
            name="db.password",
            reference=SecretReference(provider="vault", path="db/password"),
            exposure=SecretExposure.ENV,
        )
        self.catalog = SecretBindingCatalog(
            name="default", bindings=(self.binding,),
        )
        self.processor = AtlasSecretEnvironmentPostProcessor(
            registry=self.registry,
            properties=BootstrapSecretProperties(),
        )

    def tearDown(self) -> None:
        # Clean up env var that the post-processor wrote
        os.environ.pop("DB.PASSWORD", None)
        SecretRegistry.reset()

    def test_post_process_injects_env(self) -> None:
        snapshot = self.processor.post_process(self.catalog)
        self.assertEqual(snapshot.state, SecretBootstrapState.READY)
        self.assertEqual(os.environ.get("DB.PASSWORD"), "sup3rs3cr3t")
        self.assertEqual(self.processor.state, SecretBootstrapState.READY)

    def test_post_process_injects_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "secrets" / "tls.pem"
            binding = SecretBinding(
                name="tls.cert",
                reference=SecretReference(provider="vault", path="db/password"),
                exposure=SecretExposure.FILE,
                pattern=__import__(
                    "atlas_richie.secret",
                    fromlist=["SecretPropertyPattern"],
                ).SecretPropertyPattern(
                    template=str(target),
                    uppercase=False,
                ),
            )
            catalog = SecretBindingCatalog(
                name="file-cat", bindings=(binding,),
            )
            snapshot = self.processor.post_process(catalog)
            self.assertEqual(snapshot.state, SecretBootstrapState.READY)
            self.assertTrue(target.is_file())
            self.assertEqual(target.read_bytes(), b"sup3rs3cr3t")

    def test_post_process_inactive_is_noop(self) -> None:
        processor = AtlasSecretEnvironmentPostProcessor(
            registry=self.registry,
            properties=BootstrapSecretProperties(active=False),
        )
        snapshot = processor.post_process(self.catalog)
        self.assertEqual(snapshot.state, SecretBootstrapState.PENDING)
        self.assertNotIn("DB.PASSWORD", os.environ)

    def test_post_process_missing_required_raises(self) -> None:
        # Inject a binding whose reference does not exist in the
        # provider — should fail with SecretBootstrapException
        missing_binding = SecretBinding(
            name="missing",
            reference=SecretReference(provider="vault", path="absent"),
            exposure=SecretExposure.ENV,
        )
        catalog = SecretBindingCatalog(
            name="missing-cat", bindings=(missing_binding,),
        )
        from atlas_richie.secret import SecretBootstrapException
        with self.assertRaises(SecretBootstrapException):
            self.processor.post_process(catalog)
        self.assertEqual(self.processor.state, SecretBootstrapState.FAILED)


class DiscoveryTest(unittest.TestCase):
    def setUp(self) -> None:
        SecretRegistry.reset()
        self.registry = SecretRegistry.instance()
        self.factory = InMemorySecretProviderFactory()
        self.session = self.factory.create(_config(name="vault"))
        self.registry.register("vault", self.session, factory=self.factory)
        # Install a binding that references "vault"
        self.registry.install_catalog(
            SecretBindingCatalog(
                name="default",
                bindings=(SecretBinding(
                    name="k",
                    reference=SecretReference(provider="vault", path="k"),
                ),),
            ),
        )

    def tearDown(self) -> None:
        SecretRegistry.reset()

    def test_discover_static_counts(self) -> None:
        discovery = SecretProviderDiscovery(self.registry)
        result = discovery.discover_static()
        self.assertIn("vault", result.topology.providers)
        self.assertEqual(result.topology.binding_counts["vault"], 1)

    def test_require_all_reachable_passes(self) -> None:
        discovery = SecretProviderDiscovery(self.registry)
        result = discovery.require_all_reachable()
        self.assertEqual(result.unreachable, ())


class DefaultClientTest(unittest.TestCase):
    def setUp(self) -> None:
        SecretRegistry.reset()
        self.registry = SecretRegistry.instance()
        self.factory = InMemorySecretProviderFactory(name="vault")
        self.session = self.factory.create(_config(name="vault"))
        self.registry.register("vault", self.session, factory=self.factory)
        self.session.writer.put(
            SecretReference(provider="vault", path="db"),
            b"x",
        )

    def tearDown(self) -> None:
        SecretRegistry.reset()

    def test_bootstrap_resolves_all(self) -> None:
        catalog = SecretBindingCatalog(
            name="c",
            bindings=(SecretBinding(
                name="db",
                reference=SecretReference(provider="vault", path="db"),
            ),),
        )
        from atlas_richie.secret import (
            DefaultBootstrapContext,
            SecretBootstrapRequest,
        )
        client = ResolverBackedBootstrapClient(registry=self.registry)
        ctx = DefaultBootstrapContext()
        result = client.bootstrap(
            SecretBootstrapRequest(catalog=catalog),
            ctx,
        )
        self.assertEqual(len(result.missing), 0)
        self.assertIn("db", result.resolved)

    def test_bootstrap_tolerate_missing(self) -> None:
        catalog = SecretBindingCatalog(
            name="c",
            bindings=(SecretBinding(
                name="absent",
                reference=SecretReference(provider="vault", path="absent"),
            ),),
        )
        from atlas_richie.secret import (
            DefaultBootstrapContext,
            SecretBootstrapRequest,
        )
        client = ResolverBackedBootstrapClient(
            registry=self.registry,
            policy=SecretPropertyPolicy(tolerate_missing=True),
        )
        ctx = DefaultBootstrapContext()
        result = client.bootstrap(
            SecretBootstrapRequest(catalog=catalog),
            ctx,
        )
        self.assertEqual(result.missing, ("absent",))


if __name__ == "__main__":
    unittest.main()
