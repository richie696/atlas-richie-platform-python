import type { QuerySnapshot } from "../../state/queryResource";
import { ObservationQueryView } from "./ObservationQueryView";

/** Report catalog degradation without owning or suppressing the page's independent data reads. */
export function ObservationCatalogNotice<Value>({
  snapshot,
  onRetry,
  readErrorDescription,
  title,
}: {
  readonly snapshot: QuerySnapshot<Value>;
  readonly onRetry: () => void;
  readonly readErrorDescription: string;
  readonly title?: string;
}) {
  return (
    <ObservationQueryView
      snapshot={snapshot}
      onRetry={onRetry}
      descriptions={{ error: readErrorDescription }}
      title={title}
    >
      {() => null}
    </ObservationQueryView>
  );
}
