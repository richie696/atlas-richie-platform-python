import { createContext, useContext } from "react";
import type { HashNavigationController } from "./hashNavigationController";
export const HashNavigationContext = createContext<HashNavigationController | null>(null);
/** Sole app routing owner; isolated route consumers may use the native unprotected adapter. */
export const useHashNavigationController = () => useContext(HashNavigationContext);
