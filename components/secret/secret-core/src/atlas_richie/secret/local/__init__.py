"""In-process secret providers: in-memory / env / file.

中文
----
对位 Java `cn.richie696.component.secret.provider.common` 的
in-memory / env / file 三种本地实现。

- `InMemorySecretProvider` — 进程内字典;测试 / bootstrap fallback。
- `EnvSecretProvider` — 从 `os.environ` 读;只读。
- `FileSecretProvider` — 从本地文件读;支持写 / rotate / delete;
  写用 write-then-rename 保证 atomicity。

English
--------
In-process secret provider implementations. Re-exports the three
local backends and their factories.
"""

from atlas_richie.secret.local.env import EnvSecretOperations, EnvSecretProviderFactory
from atlas_richie.secret.local.file import (
    FileSecretDeletable,
    FileSecretOperations,
    FileSecretProviderFactory,
    FileSecretWriter,
)
from atlas_richie.secret.local.in_memory import (
    InMemorySecretDeletable,
    InMemorySecretOperations,
    InMemorySecretProviderFactory,
    InMemorySecretWriter,
)

__all__ = [
    "InMemorySecretProviderFactory",
    "InMemorySecretOperations",
    "InMemorySecretWriter",
    "InMemorySecretDeletable",
    "EnvSecretProviderFactory",
    "EnvSecretOperations",
    "FileSecretProviderFactory",
    "FileSecretOperations",
    "FileSecretWriter",
    "FileSecretDeletable",
]
