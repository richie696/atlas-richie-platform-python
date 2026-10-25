/** 24 uniformly chosen URL-safe characters provide 144 bits of password entropy. */
export const GENERATED_ACCOUNT_PASSWORD_LENGTH = 24;
const ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";

/** Generate locally with Web Crypto. No network, persistence, logging or weak fallback. */
export function generateAccountPassword(random: Pick<Crypto, "getRandomValues"> = crypto): string {
  const bytes = random.getRandomValues(new Uint8Array(GENERATED_ACCOUNT_PASSWORD_LENGTH));
  // 256 is divisible by 64: reducing each secure random byte introduces no modulo bias.
  return Array.from(bytes, (value) => ALPHABET[value & 63]).join("");
}
