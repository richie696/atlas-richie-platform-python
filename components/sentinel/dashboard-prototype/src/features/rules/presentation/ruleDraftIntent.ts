/** Local confirmation intents only, not backend operation kinds or stored scheduler states. */
export const RULE_DRAFT_INTENT = Object.freeze({
  Restart: "restart",
  Discard: "discard",
  Close: "close",
  Delete: "delete",
  Remove: "remove",
} as const);
export type RuleDraftIntent = (typeof RULE_DRAFT_INTENT)[keyof typeof RULE_DRAFT_INTENT];
