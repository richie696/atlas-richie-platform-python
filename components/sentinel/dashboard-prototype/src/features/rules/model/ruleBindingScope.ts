import { isObservationTime } from "../../../shared/model/observation";
import { hasNonBlankWireContent } from "../../../core/api/protocol/wireString";

export interface RuleScopeEnvironment {
  readonly id: string;
  readonly name: string;
}

export interface RuleScopeApplication {
  readonly id: string;
  readonly environmentId: string;
  readonly name: string;
}

/** Selector facts derived from persisted rule bindings, never from metric reporters. */
export interface RuleBindingScopeCatalog {
  readonly asOfMs: number;
  readonly environments: readonly RuleScopeEnvironment[];
  readonly applications: readonly RuleScopeApplication[];
}

const validText = (value: string) =>
  !!value.trim() && hasNonBlankWireContent(value) && value.length <= 200;

/** Validate sorted scope facts and their environment ownership before the Rules page consumes them. */
export function validRuleBindingScopeCatalog(value: RuleBindingScopeCatalog): boolean {
  const environmentIds = new Set(value.environments.map(({ id }) => id));
  const applicationKeys = new Set(
    value.applications.map(({ environmentId, id }) => JSON.stringify([environmentId, id])),
  );
  return (
    isObservationTime(value.asOfMs) &&
    value.environments.length <= 1000 &&
    value.applications.length <= 1000 &&
    environmentIds.size === value.environments.length &&
    applicationKeys.size === value.applications.length &&
    value.environments.every(({ id, name }) => validText(id) && validText(name)) &&
    value.applications.every(
      ({ id, environmentId, name }) =>
        validText(id) && validText(name) && environmentIds.has(environmentId),
    )
  );
}
