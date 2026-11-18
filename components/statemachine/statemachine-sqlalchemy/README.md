# atlas-richie-statemachine-sqlalchemy

状态机的关系库持久化（对位 Java `StateDbPersistenceService`）。

Java 的默认路径是 DB 持久化 + 异步批量落库 + Redis 丢失后从 DB 恢复；
此前 Python 只有 Redis 存储。本包补上耐久层。

依赖 `statemachine-core` + `sqlalchemy`（Core，无 ORM）。引擎是同步
callable 模型，存储随之同步；异步批量是吞吐优化，留待真实负载。

## 表结构

列名对位 Java Liquibase schema：`state_machine` / `business_id` /
`current_state` / `prev_state` / `curr_state` / `event_name` /
`occurred_at` / `seq`。另加 `operator` / `remark` / `attributes` 三列
承载完整上下文（Java 侧这些只在 Redis/context，落库会丢）。

序号分配用单条 `INSERT .. ON CONFLICT DO UPDATE .. RETURNING`，
PostgreSQL 与 SQLite（3.35+）均原子，多实例不会观察到撕裂值。
其他方言显式抛 NotImplementedError，不静默降级。

## Redis 丢失后恢复

```python
from atlas_richie.statemachine_sqlalchemy import (
    ReplicatingStateStorage, SqlAlchemyStateStorage,
)

db = SqlAlchemyStateStorage("postgresql+psycopg://...")
storage = ReplicatingStateStorage(primary=redis_storage, replica=db)
```

写先主后备（备失败仅记日志，主是权威，迁移不因备库故障失败）；
读先主，主**缺失或异常**时读备——键被逐出和 Redis 宕机都能从耐久层愈合。

## 用法

```python
from atlas_richie.statemachine_core import StateMachineEngine
from atlas_richie.statemachine_sqlalchemy import SqlAlchemyStateStorage

storage = SqlAlchemyStateStorage("sqlite:///states.db")
engine = StateMachineEngine(models, storage=storage, sequences=storage)
```

`SqlAlchemyStateStorage` 同时实现 `StateStorage` 与 `SequenceAllocator`。
