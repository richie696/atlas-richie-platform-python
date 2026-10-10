import type { ReactNode } from "react";
import { ReactFrameworkProvider } from "@richie696/react-framework-react";
import { AuthenticationProvider } from "../../features/identity/authentication";
import { AstryxProvider } from "./AstryxProvider";
import { NavigationBoundary } from "../router/NavigationBoundary";
import { ConsoleRuntimeProvider } from "../../core/api/runtime/ConsoleRuntimeProvider";
import type { ConsoleRuntimeConfiguration } from "../../core/api/runtime/consoleRuntimeConfiguration";
import { ConsoleServicesProvider } from "./ConsoleServicesProvider";
import { AuthenticatedSessionBridge } from "./AuthenticatedSessionBridge";
import type { ConsoleServices } from "./consoleServices";
import "../i18n/config";

// Immutable application options, not a per-render service construction.
const frameworkOptions = Object.freeze({
  baseUrl: window.location.origin,
  showLoading: false,
});

/**
 * Application-lifetime infrastructure and UI assembly. Rendering never creates
 * transport/authentication owners or framework options. Feature data is read
 * through the shared Console transport; mock/live selection stays in runtime
 * assembly and network interception.
 */
export function AppProviders({
  children,
  runtime,
  services,
}: {
  readonly children: ReactNode;
  readonly runtime: ConsoleRuntimeConfiguration;
  readonly services: ConsoleServices;
}) {
  return (
    <ReactFrameworkProvider options={frameworkOptions}>
      <ConsoleRuntimeProvider configuration={runtime}>
        <ConsoleServicesProvider services={services}>
          <AuthenticationProvider workflow={services.authentication}>
            <AuthenticatedSessionBridge>
              <AstryxProvider>
                <NavigationBoundary>{children}</NavigationBoundary>
              </AstryxProvider>
            </AuthenticatedSessionBridge>
          </AuthenticationProvider>
        </ConsoleServicesProvider>
      </ConsoleRuntimeProvider>
    </ReactFrameworkProvider>
  );
}
