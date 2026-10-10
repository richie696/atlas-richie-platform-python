/** Compile-time resource shape is derived from the canonical English JSON bundles. */
import type applications from "./messages/en-US/applications.json";
import type faults from "./messages/en-US/faults.json";
import type identity from "./messages/en-US/identity.json";
import type observation from "./messages/en-US/observation.json";
import type overview from "./messages/en-US/overview.json";
import type realtime from "./messages/en-US/realtime.json";
import type rules from "./messages/en-US/rules.json";
import type shell from "./messages/en-US/shell.json";
import type system from "./messages/en-US/system.json";

/** Flat runtime catalogue type; locale JSON remains the sole source of message keys. */
export type TranslationResources = {
  readonly translation: typeof applications &
    typeof faults &
    typeof identity &
    typeof observation &
    typeof overview &
    typeof realtime &
    typeof rules &
    typeof shell &
    typeof system;
};

/** Every key accepted by the shared i18next instance. */
export type TranslationKey = keyof TranslationResources["translation"] & string;
