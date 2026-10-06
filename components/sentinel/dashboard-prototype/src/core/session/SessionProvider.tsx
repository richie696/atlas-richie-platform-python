/**
 * 当前会话：谁在用控制台、持有哪些能力。
 *
 * 中文
 * ----
 * 会话是**应用级**状态，变化频率极低（用户切换演示身份），与 `LocaleProvider`
 * 同理：用一个只承载会话的 Context 是安全的，它不会因为每次功能交互而改变。
 *
 * ## 为什么默认给全量能力
 *
 * 控制台原型没有真实的认证后端，但**权限门禁必须是真实的**——否则
 * `useCan` 只是一层摆设，等接上后端时门禁的每个调用点都要重新验证一遍。
 *
 * 所以这里做三件事：
 *
 * 1. 能力快照默认是演示管理员（两项能力齐全），因此默认状态下界面与门禁落地
 *    之前**逐像素相同**，视觉基线不需要重采。
 * 2. 提供切换到受限会话的入口，让「缺能力时隐藏入口」这条路径可被演示、可被测试。
 * 3. 明确这是**快照**而非授权：`DASHBOARD_CONTROL_PLANE.md` §2 写的是服务端在
 *    每次请求上重新判定，界面隐藏不是安全边界。
 *
 * ## 会话不进 URL
 *
 * 与 `locale` 同理：会话是本机状态，不进可分享链接。放进 URL 会让「把只读视图
 * 发给同事」变成「把只读**权限**发给同事」，而权限必须由服务端裁决。
 *
 * 持久化用 `localStorage`，键名独立于语言偏好——两者是不同维度的本机偏好。
 */
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { ALL_CAPABILITIES, SESSION_CAPABILITY, hasCapability, type SessionCapability } from "./capabilities";

/** 会话身份键。独立于语言偏好键：两者是不同维度的本机状态。 */
const STORAGE_KEY = "sentinel.session";

/** 演示身份 id。值与 `IDENTITY_ROLE` 的角色 id 一致。 */
export type SessionRoleId = "admin" | "view";

/** 一个会话。 */
export interface Session {
  readonly roleId: SessionRoleId;
  /** 快照，不是授权。 */
  readonly capabilities: readonly SessionCapability[];
}

/**
 * 演示身份目录。
 *
 * 能力直接来自 `IDENTITY_ROLES` 的 `permissions`，不在这里另抄一份——
 * 两份表会漂移，而「权限声明与实际角色对不上」正是 §2 要防的事。
 */
const DEMO_SESSIONS: Readonly<Record<SessionRoleId, Session>> = Object.freeze({
  admin: { roleId: "admin", capabilities: ALL_CAPABILITIES },
  // 只读：能看指标，不能写规则。缺 `rules:write` 时规则页隐藏写入口。
  view: { roleId: "view", capabilities: [SESSION_CAPABILITY.MetricsView] },
});

/** 演示管理员：原型无认证后端时的默认身份。 */
export const DEFAULT_SESSION: Session = DEMO_SESSIONS.admin;

interface SessionContextValue {
  readonly session: Session;
  readonly setRole: (roleId: SessionRoleId) => void;
}

const SessionContext = createContext<SessionContextValue | null>(null);

/** 读本机会话；隐私模式或数据损坏时回落到演示管理员。 */
function readStoredSession(): Session {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw && raw in DEMO_SESSIONS) {
      return DEMO_SESSIONS[raw as SessionRoleId];
    }
  } catch {
    // 隐私模式下读不到，落到默认值即可。
  }
  return DEFAULT_SESSION;
}

export interface SessionProviderProps {
  readonly children: ReactNode;
}

/** 持有当前会话并提供切换命令。value 只在身份真正变化时才变。 */
export function SessionProvider({ children }: SessionProviderProps) {
  const [session, setSession] = useState<Session>(readStoredSession);

  const setRole = useCallback((roleId: SessionRoleId) => {
    const next = DEMO_SESSIONS[roleId] ?? DEFAULT_SESSION;
    setSession(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next.roleId);
    } catch {
      // 写不进去只影响下次刷新后的身份，不阻断本次切换。
    }
  }, []);

  const value = useMemo<SessionContextValue>(() => ({ session, setRole }), [session, setRole]);
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

function useSessionContext(): SessionContextValue {
  const value = useContext(SessionContext);
  // 缺失时报错而不是静默回落成「什么都能做」——后者会让门禁看起来在工作，
  // 实际是 Provider 忘了挂。
  if (!value) {
    throw new Error("useSession/useCan 必须在 <SessionProvider> 内使用");
  }
  return value;
}

/** 当前会话。 */
export function useSession(): Session {
  return useSessionContext().session;
}

/** 切换演示身份。接入真实认证后本命令消失，改为服务端下发会话。 */
export function useSessionRoleSetter(): (roleId: SessionRoleId) => void {
  return useSessionContext().setRole;
}

/**
 * 当前会话是否持有某项能力。
 *
 * 组件用它决定**显不显示**入口，不用来判断「能不能写」——写操作是否被接受
 * 由服务端裁决。返回布尔值而不是能力对象，是为了让调用点写成条件渲染，
 * 不给「拿能力对象顺手当参数传下去」的机会。
 */
export function useCan(required: SessionCapability): boolean {
  const { session } = useSessionContext();
  return hasCapability(session.capabilities, required);
}
