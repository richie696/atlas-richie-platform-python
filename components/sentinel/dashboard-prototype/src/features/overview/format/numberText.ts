/**
 * 总览页的数字格式化。
 *
 * 中文
 * ----
 * 单独成文件而不是塞进 `model/overview.ts`：领域模型回答「这个数字是什么口径」，
 * 格式化回答「这个数字怎么显示」。后者接入多语言后要整体换实现，前者不应该跟着变。
 *
 * 命名按能力而不是按工具箱（不使用 `utils.ts` / `helpers.ts`）：
 * 总览页的展示层目前只需要「按千分位显示一个数字」这一件事。
 */

/**
 * 按当前 locale 格式化数字；展示层格式不写进协议值。
 *
 * 中文
 * ----
 * **当前硬编码 `"zh-CN"`，这是已知缺陷，不要在本次重构里顺手"修好"**：
 * 视觉基线（`tests/visual` 的 DOM 快照与截图）依赖 `zh-CN` 的千分位与分组形态，
 * 改成跟随 `locale` 会让切到 en-US 时表格数字与基线不一致。
 *
 * 正确做法：等 `core/i18n` 的 `Translator` 落地后，由调用方把 `locale` 传进来
 * （`REWRITE_PLAN.md` §1.3），并同步更新视觉基线，而不是在这里猜一个 locale。
 */
export const numberText = (value: number): string =>
  new Intl.NumberFormat("zh-CN").format(value);
