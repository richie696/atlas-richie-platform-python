# Sentinel Console 首次安装与初始化

本文说明单机首次运行的最短路径。完整配置项、网络白名单、TLS、密钥轮换、配置发布和多 worker 限制见：

```bash
sentinel-console docs reference
```

## 1. 安装

需要 Python 3.12 或更新版本，并为 Console 数据库选择一个驱动 extra：

```bash
pip install 'atlas-richie-sentinel-console[server,postgres]'
# 或
pip install 'atlas-richie-sentinel-console[server,mysql]'
```

选择 Nacos 规则发布时，再安装 `nacos-grpc` extra。数据库服务及 Nacos/Consul、Prometheus 均由部署方提供；安装 Console 不会替用户创建这些服务。

## 2. 首次启动前准备

首次启动前，按完整配置参考准备：

- 可用的 PostgreSQL 或 MySQL 数据库，以及数据库目标白名单和所需 TLS CA。
- 部署状态目录中的 setup-window、operator authority、加密 runtime locator 和初始化锁文件路径；目录应是部署方预先创建、仅服务账户可读写的本地 POSIX 持久目录。
- 初始化幂等密钥、operator authority 指纹密钥、数据库定位加密密钥，以及账户、来源凭证和登录身份所需的独立密钥环。通过 Secret Manager 或等价的部署 Secret 注入，不要放入源码、镜像、命令行参数或日志。
- 精确的浏览器 Origin、数据库目标网络规则，以及 Nacos/Consul 的来源目标白名单。需要指标查询时，再配置 Prometheus 目标白名单。

所有必需变量都在 `sentinel-console docs reference` 的首次启动配置表中列出。Console 在缺少配置时会安全失败，不会自动选择默认数据库、创建默认管理员或猜测凭证。

## 3. 仅本机访问的初始化

本机单节点部署应保持 loopback 边界：默认绑定 `127.0.0.1:8000`，浏览器 Origin 也只允许 `localhost` 或 loopback 地址，并且不要设置可信反向代理 CIDR。启动后在本机打开 `http://127.0.0.1:8000`，按初始化向导连接数据库、创建首个管理员并登记规则来源。

若本机开发环境确实通过纯 HTTP 访问，可显式设置 `SENTINEL_CONSOLE_ALLOW_INSECURE_LOOPBACK_COOKIES=true`。启动时会强制检查监听地址和全部浏览器 Origin 都是 loopback，并改用不带 `Secure` 属性、非 `__Host-` 前缀的本地 cookie。此选项只适用于本机 HTTP；远程部署和生产环境必须使用 HTTPS，并保持默认的 Secure cookie。

当且仅当 bind、允许的 Origin 都是 loopback 且没有可信代理时，初始化流程不要求一次性 operator code；远程部署必须由运维方从受控渠道配置 operator code。不要随便输入一个值，也不要将远程服务误配置成 loopback 免码模式。

setup-window 必须由部署方显式开启：

```bash
sentinel-console setup-window status
sentinel-console setup-window open
```

初始化完成后，向导会关闭 setup；之后从登录页进入控制台。若需重新开放初始化窗口，先确认隔离与授权边界，再按参考文档操作。

## 4. 启动与检查

```bash
sentinel-console serve
```

服务默认监听 `127.0.0.1:8000`。`GET /healthz` 是不依赖数据库、配置中心或指标服务的进程健康检查；健康检查通过不代表这些依赖已配置成功。

若确需远程访问，应先配置受信 TLS 入口和明确的可信代理 CIDR，并让最靠近客户端的代理覆盖而不是透传用户提供的 `X-Forwarded-For`。不要直接将无 TLS 的 Console 端口暴露到公网。

## 5. 配置中心与主机监控

完成初始化后，可在控制台登记 Nacos 或 Consul 作为规则来源；只有明确启用并配置 publication profile、网络 grant 和密钥时，才会开放规则持久发布。Nacos gRPC TLS 与 Nacos Admin HTTP TLS 是不同配置，详见完整参考。

主机指标由 Prometheus 查询后端提供，不由 Console 直接采集。先部署并配置 Prometheus 与相应 exporter，再设置 `SENTINEL_CONSOLE_MONITORING_TARGETS` 允许目标访问，最后在“系统管理”的采集/监控配置中登记查询端点。没有采样时，监控页面应显示空数据状态，而不是把连接失败伪装成零值。

## 6. 单机与扩展边界

默认使用一个 worker。多个 worker 仅适用于同一主机、共同使用同一 SQL 数据库和本地 POSIX 状态目录的部署；NFS 或跨主机多副本不在此 CLI 组合的支持契约内。不要仅通过增加 `SENTINEL_CONSOLE_WORKERS` 或副本数来实现高可用。

## 7. 忘记内置管理员密码

如果唯一的内置管理员忘记密码，具备主机/部署权限的运维人员可在 Console 主机上，使用与服务相同的部署环境变量和状态目录运行：

```bash
sentinel-console account recover-admin
```

命令会先显示脱敏后的数据库目标，要求输入 `RECOVER` 确认，再通过终端隐藏输入两次新密码（8–32 位）。密码不会出现在命令参数、环境变量或终端回显中。成功后会更新内置管理员密码、撤销该账号的现有会话，并记录一条操作者为本机运维恢复的审计事件；账号角色和状态不会改变。

该命令只允许在 Console 主机本地运行，需要读取部署方的数据库定位密钥并能连接已初始化的数据库。它不会开放匿名 HTTP 重置接口，也不会创建新的管理员账号。若服务由 systemd、容器或 Kubernetes 管理，应以服务身份加载同一套部署 Secret/配置后，在对应运行环境执行，不要将数据库密码复制到命令行。
