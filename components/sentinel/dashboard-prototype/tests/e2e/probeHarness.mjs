/** Mount a rendered feature probe in a fresh, styled document with exactly one React root. */
export async function mountReactProbe(
  page,
  baseUrl,
  { id, modulePath, componentName, topologyFactoryName, cleanupName, topologyName, props = {} },
) {
  for (const value of [id, componentName, cleanupName, topologyName]) {
    if (!/^[A-Za-z_$][\w$-]*$/.test(value)) {
      throw new TypeError(`Invalid probe identifier: ${value}`);
    }
  }
  if (topologyFactoryName !== undefined && !/^[A-Za-z_$][\w$-]*$/.test(topologyFactoryName)) {
    throw new TypeError(`Invalid topology factory identifier: ${topologyFactoryName}`);
  }
  if (!modulePath.startsWith("/tests/e2e/probes/") || !modulePath.endsWith(".tsx")) {
    throw new TypeError(`Invalid probe module path: ${modulePath}`);
  }

  const origin = new URL(baseUrl).origin;
  await page.goto(`${origin}/tests/e2e/probes/host.html`);
  await page.waitFor(`window.__sentinelProbeReady === true`, {
    label: "isolated probe host ready",
  });
  await page.eval(`(async () => {
    const React = (await import("/node_modules/.vite/deps/react.js")).default;
    const { createRoot } = (await import("/node_modules/.vite/deps/react-dom_client.js")).default;
    const probe = await import(${JSON.stringify(modulePath)});
    const rootElement = document.getElementById("root");
    if (!rootElement || rootElement.childElementCount !== 0) throw new Error("Probe host root is not empty");
    rootElement.id = ${JSON.stringify(id)};
    const topology = ${topologyFactoryName === undefined ? "null" : `probe[${JSON.stringify(topologyFactoryName)}]()`};
    const root = createRoot(rootElement, { identifierPrefix: ${JSON.stringify(`${id}-`)} });
    root.render(React.createElement(React.StrictMode, null,
      React.createElement(probe[${JSON.stringify(componentName)}], {
        ...${JSON.stringify(props)},
        ...(topology === null ? {} : { topology }),
      }),
    ));
    window[${JSON.stringify(topologyName)}] = topology;
    window[${JSON.stringify(cleanupName)}] = () => {
      root.unmount();
      topology?.dispose();
    };
  })()`);
}
