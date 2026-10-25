import { useState } from "react";
import { useExternalSnapshot } from "@richie696/react-framework-react";
import {
  createRuleBindingDirectory,
  createStoredDraftDirectory,
  RuleBindingDirectory,
  StoredDraftCatalog,
  type BindingQuery,
} from "../../../src/features/rules/workspace";
import { AstryxProvider } from "../../../src/app/providers/AstryxProvider";
import { createRuleWorkspaceTopology, RuleSetWorkspaceProbe } from "./RuleSetWorkspaceProbe";
import { ruleSet } from "../../fixtures/ruleSets";
/** In-memory test Ports exercise formal consumers, not the production HTTP/mock assembly. */
export function createRuleDirectoryTopology() {
  const workspace = createRuleWorkspaceTopology();
  const access = { read: workspace.read.getSnapshot, subscribe: workspace.read.subscribe };
  let invalid = false;
  const bindings = [
    ruleSet.binding,
    { ...ruleSet.binding, id: "binding-two", location: "second-location" },
  ];
  const directory = createRuleBindingDirectory(
    {
      async readBindings(query) {
        const items = bindings.filter(
          (binding) =>
            (!query.kind || binding.kind === query.kind) &&
            (!query.appId || binding.appId === query.appId) &&
            binding.id.includes(query.search),
        );
        return {
          query,
          total: items.length,
          items: invalid
            ? [{ ...ruleSet.binding, environmentId: "foreign" }]
            : items.slice((query.page - 1) * query.pageSize, query.page * query.pageSize),
        };
      },
    },
    access,
  );
  const draftAccess = {
    read: () => ({
      ...workspace.read.getSnapshot(),
      allowed: workspace.read.getSnapshot().allowed && workspace.write.getSnapshot().allowed,
    }),
    subscribe(notify: () => void) {
      const read = workspace.read.subscribe(notify),
        write = workspace.write.subscribe(notify);
      return () => {
        read();
        write();
      };
    },
  };
  const drafts = createStoredDraftDirectory(
    ruleSet.binding,
    { readDrafts: workspace.readDrafts },
    draftAccess,
    workspace.operation,
  );
  return {
    workspace,
    directory,
    drafts,
    invalidate: () => {
      invalid = true;
    },
    dispose() {
      drafts.dispose();
      directory.dispose();
      workspace.dispose();
    },
  };
}
export function RuleDirectoryProbe({
  topology,
}: {
  readonly topology: ReturnType<typeof createRuleDirectoryTopology>;
}) {
  const [query, setQuery] = useState<BindingQuery>({
    environmentId: "test-env",
    appId: null,
    kind: null,
    search: "",
    page: 1,
    pageSize: 1,
  });
  const [selectedId, select] = useState<string | null>(null);
  const directory = useExternalSnapshot(topology.directory),
    drafts = useExternalSnapshot(topology.drafts);
  return (
    <AstryxProvider>
      <button data-directory-invalid onClick={topology.invalidate}>
        Invalid directory response
      </button>
      <RuleBindingDirectory
        resource={topology.directory}
        query={query}
        environments={[{ value: "test-env", label: "Test environment" }]}
        applications={[{ value: "app-one", label: "Test application" }]}
        selectedId={selectedId}
        onQueryChange={setQuery}
        onSelect={(binding) => select(binding.id)}
      />
      <StoredDraftCatalog
        bindingId={ruleSet.binding.id}
        resource={topology.drafts}
        workflow={topology.workspace.workflow}
      />
      <RuleSetWorkspaceProbe topology={topology.workspace} />
      <output data-directory-summary style={{ display: "block", overflowWrap: "anywhere" }}>
        {JSON.stringify({ selectedId, query, directory: directory.status, drafts: drafts.status })}
      </output>
    </AstryxProvider>
  );
}
