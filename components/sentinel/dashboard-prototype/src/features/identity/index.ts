/**
 * 身份 feature 的公共出口。
 *
 * 中文
 * ----
 * 一个 feature 只能通过这里被外部引用。旧实现把 5 个页面挤在
 * `ui/IdentityPages.tsx` 里，`features/system/ui/SystemPage.tsx` 直接深导入了这个私有
 * 路径——两个 feature 因此互相读取内部实现：system 一旦改名或移动，identity 就会跟着
 * 坏，依赖方向也无法从 import 语句上看出来。
 *
 * 这里只导出**路由页面**这一层最小契约：它们是应用装配（`app/App.tsx`）与跨 feature
 * 复用（system 的「账户维护 / 角色绑定」标签页）真正需要的符号。model、state、fixtures
 * 仍是本 feature 的私有实现，不对外暴露。
 */
export { AccountMaintenancePage } from "./ui/AccountMaintenancePage";
export { RoleBindingPage } from "./ui/RoleBindingPage";
export { ChangePasswordPage } from "./ui/ChangePasswordPage";
export { LoginPage } from "./ui/LoginPage";
export { SystemInitializationPage } from "./ui/SystemInitializationPage";
