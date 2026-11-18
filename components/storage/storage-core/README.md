# atlas-richie-storage-core

Object storage contracts: engine SPI, value objects, ACL vocabulary and a named
engine registry. **Zero runtime dependencies** — no SDK.

Ported from the Java `atlas-richie-storage-core`. The Java `StorageEngine`
interface carries many Java-type overloads (`File`, `InputStream`, `Collection`,
`Map`); those collapse into a small Python surface. Providers live in separate
adapter packages, so installing the core never pulls boto3 or a cloud SDK.

## SPI

```python
class ObjectStorageEngine(Protocol):
    def put_object(bucket, key, data, *, content_type=None, acl=None, metadata=None) -> UploadResult
    def get_object(bucket, key) -> DownloadResult
    def stat_object(bucket, key) -> ObjectStat
    def delete_object(bucket, key) -> bool
    def list_objects(bucket, *, prefix="", limit=1000, token=None) -> ObjectListing
    def presign_upload(bucket, key, *, expires_seconds=900, content_type=None) -> DirectUploadPolicy
    def presign_download(bucket, key, *, expires_seconds=900) -> DirectDownloadPolicy
```

`DirectUploadPolicy` / `DirectDownloadPolicy` mirror the Java beans, including
`success` / `error_message` and the `fallback` flag for a server-proxied transfer
when presigning is unavailable. Failures are returned as a policy with
`success=False`, not raised.

## ACL vocabulary

`Acl.parse` normalizes provider spellings (`public_read`, `publicread`,
`PUBLIC-READ`) to the canned S3 vocabulary, and maps
`bucket-owner-full-control` to `private` rather than silently granting public
access. An unknown value raises instead of defaulting.

## Registry

`StorageEngineRegistry` mirrors the Java registry: unique names, first registered
becomes default unless another is marked `default=True`, and lookups raise
`StorageError` for unknown names.

## Errors

`StorageError` base, `ObjectNotFoundError`, `BucketNotFoundError`. Adapters
translate provider-specific codes into these.

## Not ported

The Java image-processing beans (`ImageFormat`, `ImageOptions`), FTP/SFTP/SMB3
config beans, Spring auto-configuration/proxy factory/secret-refresh participant,
and the per-provider ACL/type converter SPI (each adapter normalizes directly).
