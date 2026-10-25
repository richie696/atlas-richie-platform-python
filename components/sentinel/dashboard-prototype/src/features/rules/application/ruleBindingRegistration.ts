import { AppError, AppErrorKind } from "@richie696/react-framework";
import { createCommandResource } from "../../../shared/state/commandResource";
import {
  createOwnedQueryResource,
  type QueryAccessObserver,
} from "../../../shared/state/ownedQueryResource";
import type { RuleSetPort } from "../api/ruleSetPort";
import {
  validRuleSourceCatalog,
  type RuleBindingRegistration,
  type RuleBindingRegistrationReceipt,
  type RuleSourceCatalog,
  type RuleSourceCatalogPort,
  validRuleBindingRegistrationReceipt,
} from "../model/ruleBindingRegistration";
import { validRuleBinding, type RuleBinding } from "../model/ruleSet";

const invalidSourceCatalog = () =>
  new AppError(AppErrorKind.PROTOCOL, "Invalid registered rule-source catalog", {
    status: 502,
    code: "rule_source_catalog_invalid",
  });
const invalidReceipt = () =>
  new AppError(AppErrorKind.PROTOCOL, "Invalid rule-binding registration receipt", {
    status: 502,
    code: "rule_binding_receipt_invalid",
  });

/** A cancellable, permission-owned read of only the source facts needed by binding registration. */
export function createRuleSourceCatalogResource(
  port: RuleSourceCatalogPort,
  access: QueryAccessObserver,
) {
  const ownerKey = access.read().ownerKey;
  const allowed = () => access.read().allowed && access.read().ownerKey === ownerKey;
  return createOwnedQueryResource<null, RuleSourceCatalog>(access, {
    keyOf: () => "rule-sources",
    async read(_query, signal) {
      if (!allowed())
        throw new AppError(AppErrorKind.FORBIDDEN, "Rule-source read access unavailable", {
          status: 403,
        });
      const catalog = await port.readSources(signal);
      if (!validRuleSourceCatalog(catalog)) throw invalidSourceCatalog();
      if (!allowed())
        throw new AppError(AppErrorKind.FORBIDDEN, "Rule-source read access unavailable", {
          status: 403,
        });
      return catalog;
    },
    classify: (catalog) => (catalog.items.length ? "ready" : "empty"),
  });
}

/** Command input binds a form submission to the exact source snapshot shown to the operator. */
export interface RuleBindingRegistrationInput {
  readonly command: RuleBindingRegistration;
  readonly sourceCatalog: RuleSourceCatalog;
}

/**
 * Admin-scoped registration command. It rejects stale source revisions before transport, verifies
 * the returned binding identity, and does not expose raw transport/server messages to the UI.
 */
export function createRuleBindingRegistrationCommand(
  port: Pick<RuleSetPort, "registerBinding">,
  access: QueryAccessObserver,
) {
  const ownerKey = access.read().ownerKey;
  const allowed = () => access.read().allowed && access.read().ownerKey === ownerKey;
  return createCommandResource<RuleBindingRegistrationInput, RuleBinding>(
    async ({ command, sourceCatalog }, signal) => {
      if (!allowed())
        throw new AppError(AppErrorKind.FORBIDDEN, "Rule-binding write access unavailable", {
          status: 403,
        });
      const source = sourceCatalog.items.find((item) => item.id === command.sourceId);
      if (
        !source ||
        source.revision !== command.sourceRevision ||
        source.provider !== command.target.provider
      )
        throw new AppError(AppErrorKind.SERVER, "Registered rule source changed", {
          status: 409,
          code: "conflict",
        });
      try {
        const binding = await port.registerBinding(command, signal);
        if (!allowed() || signal.aborted) throw invalidReceipt();
        if (
          !validRuleBinding(binding) ||
          binding.id !== command.bindingId ||
          binding.environmentId !== command.environmentId ||
          binding.appId !== command.appId ||
          binding.kind !== command.kind ||
          binding.profile !== command.profile ||
          binding.sourceId !== command.sourceId
        )
          throw invalidReceipt();
        return binding;
      } catch (cause) {
        const error = AppError.fromUnknown(cause);
        const code =
          error.code &&
          [
            "conflict",
            "forbidden",
            "unauthenticated",
            "csrf_failed",
            "idempotency_conflict",
            "validation_failed",
            "service_unavailable",
            "rule_binding_receipt_invalid",
          ].includes(error.code)
            ? error.code
            : undefined;
        throw new AppError(error.kind, "Rule-binding registration failed", {
          status: error.status,
          code,
        });
      }
    },
  );
}

/** Correlated parameters for a read-only inspection of an unknown create outcome. */
export interface RuleBindingRegistrationLookup {
  readonly bindingId: string;
  readonly requestKey: string;
}

/**
 * Session-owned receipt lookup for the exact original create request. `not_found` remains an
 * unknown write outcome; this resource never calls registerBinding or changes command state.
 */
export function createRuleBindingRegistrationReceiptResource(
  port: Pick<RuleSetPort, "readBindingRegistration">,
  access: QueryAccessObserver,
) {
  const ownerKey = access.read().ownerKey;
  const allowed = () => access.read().allowed && access.read().ownerKey === ownerKey;
  return createOwnedQueryResource<RuleBindingRegistrationLookup, RuleBindingRegistrationReceipt>(
    access,
    {
      keyOf: ({ bindingId, requestKey }) => JSON.stringify([bindingId, requestKey]),
      async read(query, signal) {
        if (!allowed())
          throw new AppError(AppErrorKind.FORBIDDEN, "Rule-binding receipt access unavailable", {
            status: 403,
          });
        const receipt = await port.readBindingRegistration(
          query.bindingId,
          query.requestKey,
          signal,
        );
        if (!validRuleBindingRegistrationReceipt(receipt, query.requestKey, query.bindingId))
          throw invalidReceipt();
        if (!allowed() || signal.aborted)
          throw new AppError(AppErrorKind.CANCELLED, "Rule-binding receipt owner changed");
        return receipt;
      },
      classify: (receipt) => (receipt.status === "completed" ? "ready" : "empty"),
    },
  );
}
