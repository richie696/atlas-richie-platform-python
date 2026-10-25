export interface SystemSettingsSnapshot {
  readonly timeZone: string;
  readonly revision: number;
}

/** Feature-owned boundary for reading and updating durable Console display settings. */
export interface SystemSettingsPort {
  read(signal: AbortSignal): Promise<SystemSettingsSnapshot>;
  updateTimeZone(timeZone: string, signal: AbortSignal): Promise<SystemSettingsSnapshot>;
}
