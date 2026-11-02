/**
 * 浏览器平台原语：生成随机标识。
 *
 * 中文
 * ----
 * `crypto.randomUUID()` 只在安全上下文暴露。以明文 HTTP 提供服务的内网 origin
 * （例如 `http://10.20.1.86:4173`）不是安全上下文，调用它会直接抛错，请求根本发不出去。
 * `crypto.getRandomValues()` 在非安全上下文同样可用，因此缺失原生方法时用它拼出同构的
 * v4 UUID：版本位、变体位与原生实现一致，输出格式逐字节相同，调用方无需区分来源。
 */

/** 返回一个 36 字符的 v4 UUID；安全上下文下直接复用原生实现。 */
export function randomUuid(): string {
  if (typeof globalThis.crypto?.randomUUID === "function") return globalThis.crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
