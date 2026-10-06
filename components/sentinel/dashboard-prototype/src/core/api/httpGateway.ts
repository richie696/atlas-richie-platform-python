/**
 * HTTP 版控制台网关。
 *
 * 中文
 * ----
 * 按 `docs/CONSOLE_API_CONTRACT.md` 实现：端点见 §6、错误码见 §7、五项决策见 §8
 * （schema 差异由本层吸收、历史中文 `scope` 在读取时兼容、回执身份用 `instanceId`、
 * 指标查询参数化、乐观锁用 `version`）。
 *
 * ## 为什么页面拿不到它
 *
 * 页面通过 {@link useConsoleGateway} 取实现，默认是 `fixtureGateway`。本模块在
 * 控制面服务就绪前不会被装配，因此**它是可运行的代码而不是已接通的链路**——
 * 端点路径与错误约定来自契约文档，真实可用性取决于后端是否按同一份契约实现。
 *
 * ## 错误映射
 *
 * HTTP 状态码 → {@link ApiErrorCode}（契约 §7）。**`403` 与「没有数据」必须
 * 可区分**：把无权渲染成空图，就是用 0 值伪装无流量。响应体里带
 * `error.code` 时以它为准，否则回落到状态码映射。
 */
import { ApiError, type ConsoleGateway, type MetricQuery, type ScopedMetric } from "./contracts";
import type { ApplicationRecord } from "../../features/applications/model/instance";
import type { ApplicationSummary, FleetAttention, InfraStatus } from "../../features/overview/model/overview";

/** 控制面服务基址。装配时注入，不写死在模块里。 */
export interface HttpGatewayOptions {
  readonly baseUrl: string;
  /** 会话凭据。接入 Cookie 会话时传 `credentials: "include"`，这里留空即可。 */
  readonly token?: string;
  /** 单次请求超时（毫秒）。 */
  readonly timeoutMs?: number;
  readonly fetchImpl?: typeof fetch;
}

const DEFAULT_TIMEOUT_MS = 15_000;

/** 契约 §7 的状态码映射。响应体带 `error.code` 时以它为准。 */
const STATUS_TO_CODE: Readonly<Record<number, ApiError["code"]>> = Object.freeze({
  400: "validation_failed",
  401: "unauthenticated",
  403: "capability_denied",
  409: "version_conflict",
  422: "readback_mismatch",
  503: "config_center_unavailable",
});

/** 服务端返回的错误体形状。字段都是可选的——它来自外部，不能假设齐备。 */
interface ErrorBody {
  readonly error?: {
    readonly code?: string;
    readonly message?: string;
    readonly capability?: string;
    readonly issues?: readonly { field: string; message: string }[];
  };
}

/**
 * 历史中文 `scope` 值 → 协议值（契约 §8.2）。
 *
 * 写入端一律用协议值；这里只处理**读取**存量配置。中文值是从旧实现泄漏出来的
 * （`RULE_SCOPE` 曾是 `{ Application: "应用" }`），配置中心里可能仍有流通。
 * 未识别的值原样返回，不静默丢弃——丢弃会让生效范围悄悄变成空。
 */
const LEGACY_SCOPE: Readonly<Record<string, string>> = Object.freeze({
  应用: "application",
  资源: "resource",
});

export function normalizeScope(value: string): string {
  return LEGACY_SCOPE[value] ?? value;
}

export class HttpConsoleGateway implements ConsoleGateway {
  readonly #baseUrl: string;
  readonly #token: string | undefined;
  readonly #timeoutMs: number;
  readonly #fetch: typeof fetch;

  constructor(options: HttpGatewayOptions) {
    this.#baseUrl = options.baseUrl.replace(/\/$/, "");
    this.#token = options.token;
    this.#timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    this.#fetch = options.fetchImpl ?? globalThis.fetch.bind(globalThis);
  }

  /** 契约 §6 `/rules/snapshot`：权威完整快照。 */
  async getRuleSnapshot(): Promise<unknown> {
    return this.#get("/rules/snapshot");
  }

  /** 契约 §6 `/system/connections`：连通性与能力边界。 */
  async getConnections(): Promise<readonly InfraStatus[]> {
    const raw = await this.#get<{ connections?: readonly InfraStatus[] }>("/system/connections");
    return raw.connections ?? [];
  }

  /** 契约 §6 `/system/permissions`：角色与能力声明。 */
  async getPermissions(): Promise<readonly { roleId: string; capabilities: readonly string[] }[]> {
    const raw = await this.#get<{
      permissions?: readonly { roleId: string; capabilities: readonly string[] }[];
    }>("/system/permissions");
    return raw.permissions ?? [];
  }

  /**
   * 契约 §6 `/metrics/query`。
   *
   * 查询参数按 §8.4 冻结；**响应形状留给后端**，但 §4 的口径字段必须存在，
   * 否则返回体缺 `unit` / `scope` / `source` 时直接抛错而不是当成 0 值——那是
   * 「用 0 值伪装无流量」最容易发生的地方。
   */
  async queryMetrics(query: MetricQuery): Promise<ScopedMetric> {
    const params = new URLSearchParams({ window: query.range });
    if (query.appId) params.set("app", query.appId);
    if (query.resource) params.set("resource", query.resource);
    return this.#get<ScopedMetric>(`/metrics/query?${params.toString()}`);
  }

  /** 总览页读模型：`/metrics/query` 与 `/system/connections` 的组合（契约 §6 注）。 */
  async getFleetOverview(): Promise<{
    applications: readonly ApplicationSummary[];
    attention: FleetAttention;
    infra: readonly InfraStatus[];
  }> {
    const raw = await this.#get<{
      applications?: readonly ApplicationSummary[];
      attention?: FleetAttention;
    }>("/fleet/overview");
    return {
      applications: raw.applications ?? [],
      attention: raw.attention as FleetAttention,
      infra: await this.getConnections(),
    };
  }

  /** 应用与实例页读模型。 */
  async getApplications(): Promise<readonly ApplicationRecord[]> {
    const raw = await this.#get<{ applications?: readonly ApplicationRecord[] }>("/applications");
    return raw.applications ?? [];
  }

  async #get<T>(path: string, init?: RequestInit): Promise<T> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.#timeoutMs);
    try {
      const response = await this.#fetch(`${this.#baseUrl}/api/v1${path}`, {
        ...init,
        signal: controller.signal,
        headers: {
          Accept: "application/json",
          ...(this.#token ? { Authorization: `Bearer ${this.#token}` } : {}),
          ...init?.headers,
        },
        // 接入 Cookie 会话时用 `include`；Bearer token 模式下留 `same-origin` 亦可。
        credentials: "include",
      });

      if (!response.ok) throw await toApiError(response);

      if (response.status === 204) return undefined as T;
      return (await response.json()) as T;
    } catch (error) {
      if (error instanceof ApiError) throw error;
      // 超时与网络故障都不是服务端的能力判断，不能伪装成「没有数据」。
      if (error instanceof Error && error.name === "AbortError") {
        throw new ApiError("config_center_unavailable", `请求超时：${path}`);
      }
      throw new ApiError("config_center_unavailable", `控制面不可达：${path}（${String(error)}）`);
    } finally {
      clearTimeout(timer);
    }
  }
}

/**
 * 错误响应 → {@link ApiError}。
 *
 * 中文
 * ----
 * 优先取响应体里的 `error.code`——它是服务端的真实语义；缺失时才回落到状态码映射。
 * 直接把状态码当结论会在网关返回 `502`（未列在契约里）时丢掉真实原因。
 */
async function toApiError(response: Response): Promise<ApiError> {
  let body: ErrorBody | undefined;
  try {
    body = (await response.json()) as ErrorBody;
  } catch {
    // 非 JSON 错误体（HTML 错误页等）——用状态码兜底。
  }
  const serverCode = body?.error?.code;
  const code =
    (serverCode as ApiError["code"] | undefined) ??
    STATUS_TO_CODE[response.status] ??
    "config_center_unavailable";
  return new ApiError(
    code,
    body?.error?.message ?? `${response.status} ${response.statusText}`,
    body?.error?.capability,
    body?.error?.issues,
  );
}