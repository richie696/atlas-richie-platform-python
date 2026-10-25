/**
 * Route-lazy login page entry. It reads the application-scoped authentication provider and calls
 * `onAuthenticated` only after an independently confirmed session; `onSetupRequired` is emitted
 * for confirmed first-run setup. The caller owns safe return navigation. Import only from the
 * lazy login route so other identity workflows do not eagerly load login UI.
 */
export { LoginEntryPage } from "./ui/LoginEntryPage";
