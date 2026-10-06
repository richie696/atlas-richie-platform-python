/**
 * 会话与能力检查的公共入口。
 *
 * 中文
 * ----
 * 与 `core/i18n` 同样的边界：这里只提供「当前会话是谁、能不能看某个入口」，
 * **不提供**「能不能写」的判断——那是服务端的事（`DASHBOARD_CONTROL_PLANE.md` §2）。
 */
export {
  ALL_CAPABILITIES,
  SESSION_CAPABILITY,
  hasCapability,
  type SessionCapability,
} from "./capabilities";
export {
  DEFAULT_SESSION,
  SessionProvider,
  useCan,
  useSession,
  useSessionRoleSetter,
  type Session,
  type SessionRoleId,
} from "./SessionProvider";
