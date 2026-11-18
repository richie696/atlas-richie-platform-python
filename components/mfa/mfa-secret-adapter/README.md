# atlas-richie-mfa-secret-adapter

把 `mfa-validation` 的 `SecretRetriever` 桥接到 `secret-core` 的
`SecretOperations`，使 MFA 的 TOTP 密钥可以从任一 secret provider
（Redis / Vault / OpenBao / KMS…）读取，而两个包互不依赖。

## 引用格式

`"provider:path"`，按第一个 `:` 拆分；配置 `default_provider` 后裸路径也
可解析。

## 错误映射

| secret-core | 桥接结果 |
|---|---|
| `SecretIntegrityException`（未找到） | `None` —— 视为「该用户未配置 MFA」 |
| 其它 `SecretException`（配置/解密错误） | 原样上抛，不得伪装成「未配置」 |

注意：redis provider 把连接故障也包装为 `SecretIntegrityException`，因此
outage 时本桥接返回 `None`，验证按「无密钥」失败关闭——安全但原因失真，
详见该 provider 的错误映射。

## 用法

```python
from atlas_richie.mfa_secret_adapter import SecretStoreSecretRetriever
from atlas_richie.mfa_validation import DefaultMfaValidationService

retriever = SecretStoreSecretRetriever(operations, default_provider="vault-main")
service = DefaultMfaValidationService(..., secret_retriever=retriever)
```
