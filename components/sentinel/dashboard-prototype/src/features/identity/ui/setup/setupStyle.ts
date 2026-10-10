import identityStyles from "../Identity.module.scss";
import actionButtonStyles from "../../../../shared/ui/ActionButton.module.scss";
import { scopedClasses } from "../../../../shared/ui/styles/scopedClasses";

const modules = [identityStyles, actionButtonStyles] as const;
/** Setup-only semantic hooks retain their owned styles when steps move between containers. */
export const setupClass = (names: string) => scopedClasses(modules, names);
