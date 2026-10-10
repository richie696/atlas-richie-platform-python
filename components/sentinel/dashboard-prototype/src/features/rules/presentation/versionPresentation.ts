/** Presentation metadata owned by this feature; never part of a wire/domain contract. */
import { VERSION_STATE, type VersionState } from "../model/ruleVersion";

/** 版本状态到状态标签色的映射。 */
export const VERSION_STATE_TONE: Readonly<Record<VersionState, string>> = Object.freeze({
  [VERSION_STATE.Active]: "healthy",
  [VERSION_STATE.Scheduled]: "blue",
  [VERSION_STATE.Superseded]: "info",
});
