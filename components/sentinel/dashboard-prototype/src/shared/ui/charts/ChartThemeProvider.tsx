import {
  createContext,
  useContext,
  useLayoutEffect,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { createChartThemeStore } from "./chartThemeStore";

const ChartThemeContext = createContext<ReturnType<typeof createChartThemeStore> | null>(null);

/** The skin owner changes revision after installing its CSS; charts never watch arbitrary DOM mutations. */
export function ChartThemeProvider({
  children,
  revision,
}: {
  readonly children: ReactNode;
  readonly revision: string | number;
}) {
  const [store] = useState(() => createChartThemeStore());
  useLayoutEffect(() => {
    store.refresh();
  }, [store, revision]);
  return <ChartThemeContext.Provider value={store}>{children}</ChartThemeContext.Provider>;
}

/** Subscribe once to the owning provider; unmount removes the subscription through React. */
export function useChartTokens() {
  const store = useContext(ChartThemeContext);
  if (!store) throw new Error("TrendChart requires ChartThemeProvider");
  return useSyncExternalStore(store.subscribe, store.getSnapshot, store.getServerSnapshot);
}
