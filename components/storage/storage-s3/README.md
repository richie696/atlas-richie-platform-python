# atlas-richie-storage-s3

S3-compatible `ObjectStorageEngine` adapter: AWS S3, MinIO, RustFS and peers.
Depends on `boto3` and `storage-core`.

## Usage

```python
from atlas_richie.storage_s3 import S3StorageEngine

# AWS S3
engine = S3StorageEngine(region_name="ap-northeast-1")

# MinIO / RustFS: explicit endpoint + path-style addressing
engine = S3StorageEngine(
    endpoint_url="http://127.0.0.1:9000",
    aws_access_key_id="minioadmin",
    aws_secret_access_key="minioadmin",
    force_path_style=True,
)

engine.put_object("bucket", "a.txt", b"hello", content_type="text/plain")
result = engine.get_object("bucket", "a.txt")
policy = engine.presign_upload("bucket", "upload.bin", expires_seconds=600)
```

Credentials may be omitted to use the standard boto3 provider chain.

## Behaviour

- SigV4 presigning is delegated to boto3; no signing logic is reimplemented.
- `delete_object` reports whether the object existed beforehand (S3 delete is
  idempotent, so a HEAD precedes it).
- Provider error codes are translated: `NoSuchKey`/`404` → `ObjectNotFoundError`,
  `NoSuchBucket` → `BucketNotFoundError`, anything else → `StorageError`.
- `list_objects` exposes continuation tokens for pagination.
- Presign failures return a policy with `success=False` and `error_message`,
  matching the Java contract, rather than raising.

## Tests

Core contract tests run offline against an in-memory engine. Adapter tests run
against a **real S3-compatible endpoint** and skip cleanly when none is reachable;
point `ATLAS_RICHIE_STORAGE_S3_URL` / `_ACCESS_KEY` / `_SECRET_KEY` at yours.
Presigned URLs are exercised end-to-end with an actual HTTP PUT and GET, not just
asserted to be non-empty strings.
