import React from "react";
import { createRoot } from "react-dom/client";
import { ReactFrameworkProvider } from "@richie696/react-framework-react";
import { App } from "./App";
import { AstryxProvider } from "./app/providers/AstryxProvider";
import "./app/i18n/config"; // i18next 初始化（副作用导入）
import { SessionProvider } from "./core/session";
import { ConsoleGatewayProvider } from "./core/api/GatewayProvider";
import { fixtureGateway } from "./core/api/fixtureGateway";
import "./styles.css";

const frameworkOptions = Object.freeze({
  baseUrl: window.location.origin,
  showLoading: false,
});

const rootElement = document.getElementById("root");

if (!rootElement) {
  throw new Error("Dashboard root element is missing.");
}

createRoot(rootElement).render(
  <React.StrictMode>
    <ReactFrameworkProvider options={frameworkOptions}>
        {/*
          SessionProvider 持有当前演示身份与它的能力快照。门禁默认给全量能力，
          因此界面与门禁落地前逐像素相同；切换到只读身份才隐藏写入口。
          详见 `core/session/SessionProvider.tsx`。
        */}
        <SessionProvider>
          {/* 控制面服务就绪后，把 gateway 换成 `new HttpConsoleGateway({ baseUrl })`。
              页面不感知实现，它们只通过 `useConsoleGateway()` 取。 */}
          <ConsoleGatewayProvider gateway={fixtureGateway}>
            <AstryxProvider>
              <App />
            </AstryxProvider>
          </ConsoleGatewayProvider>
        </SessionProvider>
    </ReactFrameworkProvider>
  </React.StrictMode>,
);
