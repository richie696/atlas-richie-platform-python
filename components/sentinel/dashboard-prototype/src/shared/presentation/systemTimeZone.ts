/** Global display-zone state. API timestamps remain UTC instants. */
let currentTimeZone = "Asia/Shanghai";
const listeners = new Set<() => void>();

export function getSystemTimeZone(): string {
  return currentTimeZone;
}

export function setSystemTimeZone(value: string): void {
  if (currentTimeZone === value) return;
  currentTimeZone = value;
  for (const listener of listeners) listener();
}

export function subscribeSystemTimeZone(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
