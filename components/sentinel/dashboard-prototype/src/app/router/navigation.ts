/**
 * 主导航的图标绑定。
 *
 * 中文
 * ----
 * 图标与路由的关系由本表唯一确定。旧实现在 `App.tsx` 里用一个平行数组
 * `NAV_ICONS[index]` 配 `PAGE_ITEMS` 的下标：新增、删除或重排导航项会让图标
 * 静默错位，而且 TypeScript 无法发现——数组长度不匹配也不会报错。
 *
 * 这里改为按 `RouteId` 显式映射，并用一个编译期约束保证「每个主导航路由都有图标」：
 * 类型是 `Record<MainNavRouteId, Icon>`，少一个键就编译不过，多一个键同样编译不过。
 * 标注文案不在本表内，见 `route.constants.ts` 的 `i18nKey`。
 */
import {
  ActivityIcon,
  GearSixIcon,
  SlidersHorizontalIcon,
  SquaresFourIcon,
  StackIcon,
  WarningIcon,
} from "@phosphor-icons/react";
import type { Icon } from "@phosphor-icons/react";

import {
  MAIN_NAVIGATION,
  type MainNavRouteId,
  type RouteId,
} from "./route.constants";

/** 每个主导航路由的图标。缺项或多项都会导致类型检查失败。 */
export const NAVIGATION_ICONS: Readonly<Record<MainNavRouteId, Icon>> = Object.freeze({
  overview: SquaresFourIcon,
  applications: StackIcon,
  rules: SlidersHorizontalIcon,
  realtime: ActivityIcon,
  faults: WarningIcon,
  system: GearSixIcon,
});

/** 按顺序返回可直接渲染的导航项，已附图标。 */
export function navigationItemsWithIcons(): readonly {
  readonly id: RouteId;
  readonly path: string;
  readonly i18nKey: string;
  readonly icon: Icon;
}[] {
  return MAIN_NAVIGATION.map((item) => {
    // MAIN_NAVIGATION 与 MAIN_NAVIGATION_IDS 出自同一张静态表，主导航 id 必然在图标表中。
    const icon = NAVIGATION_ICONS[item.id as MainNavRouteId];
    return { id: item.id, path: item.path, i18nKey: item.i18nKey, icon };
  });
}
