/**
 * 翻译函数的类型契约。
 *
 * 中文
 * ----
 * 键的**存在性**由 `npm run i18n:check` 在 CI 里校验：`TFunction` 的 key 是 `string`，
 * `t("ovrview.title")` 拼错在编译期无声无息。这是用 JSON 换翻译平台可读性时
 * 有意识付出的代价，靠 CI 而不是靠人记补回来。
 */

/** 单个 locale 下的扁平消息表。 */
export type MessageBundle = Readonly<Record<string, string>>;

/** 翻译函数的插值参数。 */
export type MessageValues = Readonly<Record<string, string | number>>;

/**
 * 页面内使用的翻译函数。
 *
 * 中文
 * ----
 * 签名与 `react-i18next` 的 `t(key, options?)` 兼容。
 */
export type Translate = (key: string, values?: MessageValues) => string;
