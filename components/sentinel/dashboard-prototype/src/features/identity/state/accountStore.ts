/**
 * 账号列表的 feature store：唯一所有者 + React 订阅适配。
 *
 * 中文
 * ----
 * **这个 store 修掉了一个真实的 state 归属 bug。** 旧实现在 `AccountMaintenancePage`
 * 和 `RoleBindingPage` 里各自 `useState` 了一份 `INITIAL_ACCOUNTS` 副本，于是
 * 「在账户维护页新建的账号」在「角色绑定页」里不存在，「在角色绑定页改的角色」在
 * 回到账户维护页后又变回原值——同一份事实有两个所有者，组件生命周期一变就读到不同
 * 的内容。
 *
 * 现在账号列表只有一份，归属规则也变成单句：**列表与状态迁移属于 store，页面只发
 * 命令**。React 通过 `useSyncExternalStore` 订阅，不再把同一份数据抄进第二份
 * `useState`，也不需要用 effect 手工同步。
 *
 * 契约（`REACT_CODING_STANDARD` §3）：
 *
 * - `getSnapshot()` 在没有变化时返回**同一个引用**，否则每次渲染都会触发比较失败；
 * - `subscribe()` 返回取消函数，React 卸载后不再收到通知；
 * - store 不依赖 React，也不 import `fixtures/`。它不知道数据从哪来。
 */
import { useCallback, useSyncExternalStore } from "react";

import type { AccountStatus, AccountSummary, IdentityRoleId } from "../model/account";

/** 不可变快照。`accounts` 引用在无变化时保持稳定。 */
export interface AccountSnapshot {
  readonly accounts: readonly AccountSummary[];
}

/** 订阅者。返回的取消函数必须可重复调用。 */
export type AccountListener = () => void;

/**
 * 账号列表的读写契约。
 *
 * 写入一律通过命令，不暴露可变数组：调用方拿不到「就地修改快照」的机会。
 */
export interface AccountStore {
  getSnapshot: () => AccountSnapshot;
  subscribe: (listener: AccountListener) => () => void;
  /** 装载账号快照。生产实现由 `identity.gateway` 在会话建立后调用。 */
  load: (accounts: readonly AccountSummary[]) => void;
  /** 新增一个账号。 */
  add: (account: AccountSummary) => void;
  /** 设置账号状态；未知 id 是无操作，不静默创建新账号。 */
  setStatus: (id: string, status: AccountStatus) => void;
  /** 绑定角色；未知 id 是无操作。 */
  setRole: (id: string, roleId: IdentityRoleId) => void;
}

/** 创建一个账号 store。工厂保持独立，便于测试用独立实例。 */
export function createAccountStore(): AccountStore {
  const listeners = new Set<AccountListener>();
  let snapshot: AccountSnapshot = Object.freeze({ accounts: Object.freeze([]) });

  // 唯一的状态迁移入口：产生新快照并通知订阅者。内容未变化时不换引用。
  const commit = (accounts: readonly AccountSummary[]) => {
    if (accounts === snapshot.accounts) return;
    snapshot = Object.freeze({ accounts: Object.freeze([...accounts]) });
    for (const listener of listeners) listener();
  };

  const update = (id: string, patch: (account: AccountSummary) => AccountSummary) => {
    commit(
      snapshot.accounts.map((account) => (account.id === id ? patch(account) : account)),
    );
  };

  return {
    getSnapshot: () => snapshot,
    subscribe: (listener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    load: (accounts) => {
      commit(Object.freeze([...accounts]));
    },
    add: (account) => {
      commit([...snapshot.accounts, account]);
    },
    setStatus: (id, status) => {
      update(id, (account) =>
        account.status === status ? account : { ...account, status },
      );
    },
    setRole: (id, roleId) => {
      update(id, (account) =>
        account.roleId === roleId ? account : { ...account, roleId },
      );
    },
  };
}

/**
 * 进程内唯一的账号 store。
 *
 * 单例是有意选择：账号列表是 feature 范围事实，跨页面（账户维护 / 角色绑定 / 改密）
 * 共享同一份。两个页面各自持有副本正是旧实现的 bug 来源。
 */
export const accountStore: AccountStore = createAccountStore();

/**
 * 装载账号快照的模块级装配命令。
 *
 * 演示装配由页面在**模块初始化时**传入 `fixtures/` 的示例列表；接入 Console API 后
 * 改为在会话建立后调用 `accountStore.load(gateway 快照)`，页面不再需要知道数据来源。
 */
export function loadAccounts(accounts: readonly AccountSummary[]): void {
  accountStore.load(accounts);
}

/** 页面消费的账号列表视图。 */
export interface AccountList {
  readonly accounts: readonly AccountSummary[];
  add: (account: AccountSummary) => void;
  setStatus: (id: string, status: AccountStatus) => void;
  setRole: (id: string, roleId: IdentityRoleId) => void;
}

/**
 * 订阅账号列表。
 *
 * Hook 只负责 React 生命周期：订阅、取消订阅，以及把 store 命令原样交给页面。
 * 它不做派生筛选、不缓存副本——需要派生值时在组件里直接算，避免第二份事实。
 */
export function useAccounts(): AccountList {
  const accounts = useSyncExternalStore(
    accountStore.subscribe,
    accountStore.getSnapshot,
    accountStore.getSnapshot,
  ).accounts;

  const add = useCallback<AccountList["add"]>(
    (account) => {
      accountStore.add(account);
    },
    [],
  );
  const setStatus = useCallback<AccountList["setStatus"]>(
    (id, status) => {
      accountStore.setStatus(id, status);
    },
    [],
  );
  const setRole = useCallback<AccountList["setRole"]>(
    (id, roleId) => {
      accountStore.setRole(id, roleId);
    },
    [],
  );

  return { accounts, add, setStatus, setRole };
}
