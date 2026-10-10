/** Narrow account/role entry; transport and application assembly are injected by the app. */
export { createAccountManagementWorkflow } from "./application/accountManagementWorkflow";
export type { AccountManagementWorkflow } from "./application/accountManagementWorkflow";
export type {
  AccountManagementPort,
  AccountMutation,
  AccountOperationObservation,
} from "./api/accountManagementPort";
export type { AccountRecord, AccountPage, AccountListQuery } from "./model/accountManagement";
export { AccountsPage } from "./ui/AccountsPage";
export { RoleManagementPage } from "./ui/RoleManagementPage";
