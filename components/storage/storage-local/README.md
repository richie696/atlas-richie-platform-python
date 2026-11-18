# atlas-richie-storage-local

本地文件系统对象存储引擎，实现 `storage-core` 的 `ObjectStorageEngine` 协议。

**纯标准库**，只依赖 `storage-core`（亦零第三方依赖）。这是唯一不需要任何
外部服务就能跑的 provider，适合开发、测试与 CI。

对位 Java `atlas-richie-storage-local`。两处有意差异：

- 元数据存在对象旁的 sidecar JSON（`<key>.atlas-meta.json`），而非 MyBatis 表
  + GlobalCache，因此无数据库/缓存依赖。
- **不支持 presign**：本地文件系统没有可签名的 URL 语义，`presign_*` 返回
  失败策略，而不是伪造一个看起来能用的地址。

## 安全

- key 禁止 `..`、`:`、绝对路径（与 Java `isSafeKey` 一致）；
- 解析真实路径后再次确认落在 bucket 根内，挡住符号链接逃逸；
- 写入走同目录临时文件 + `os.replace` 原子替换，读者看不到半个对象；
- 超过 `max_size` 立即失败并清理临时文件。

## 用法

```python
from atlas_richie.storage_local import LocalStorageEngine

engine = LocalStorageEngine("/tmp/objects", max_size=10 * 1024 * 1024)
engine.create_bucket("uploads")
engine.put_object("uploads", "a/b.txt", b"hello", content_type="text/plain")
with engine.get_object("uploads", "a/b.txt").stream as fh:
    print(fh.read())
print(engine.list_objects("uploads", prefix="a/").keys)
```