/**
 * 实例矩阵的数字格式化。
 *
 * 中文
 * ----
 * 与其它纯函数同放 `model/`：格式化是纯计算，没有 React、语言包或网络依赖。等第二个
 * feature 需要同一份格式化时，再上提到 `shared/format/`（`REACT_PROJECT_SKELETON` §2：
 * 共享目录在第二个真实消费者出现后再建）。
 *
 * 为什么 locale 写死
 * ----------------
 * `zh-CN` 是当前原型的硬编码，视觉基线依赖它（`1,240` 这类分组样式），本轮不能改。
 * 接入多语言后应改为按 session locale 格式化：`Intl.NumberFormat(locale)`，并把展示
 * 格式与协议值（`qps` 原始数字）分开——现在这一点已经成立，本函数只接收数字、返回
 * 字符串。
 *
 * 旧实现把这段放在全局 `demoData` 里与应用、实例数据混放，于是「数字怎么排版」这件与
 * 演示数据毫无关系的事跟着数据文件一起被跨 feature 引用。
 */
const INSTANCE_NUMBER_FORMAT = new Intl.NumberFormat("zh-CN");

/** 按当前界面语言的数字分组格式输出。 */
export function formatInstanceNumber(value: number): string {
  return INSTANCE_NUMBER_FORMAT.format(value);
}
