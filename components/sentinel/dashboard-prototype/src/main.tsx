import React from "react";
import { createRoot } from "react-dom/client";
import { ReactFrameworkProvider } from "@richie696/react-framework-react";
import { App } from "./App";
import { AstryxProvider } from "./app/providers/AstryxProvider";
import { LocaleProvider } from "./core/i18n/useTranslator";
import { SessionProvider } from "./core/session";
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
        LocaleProvider 自己持有 locale 状态：首屏从 `sentinel.locale` 读，之后由
        语言下拉的命令更新并写回。

        旧实现在这里传一个模块加载时算出的 `initialLocale` 常量，Provider 就再也不
        变；而 App 内部另有一份活的 useState，于是同一个 locale 存在两份——壳层
        用新的一份（切语言生效），用 useTranslator 的页面读旧的一份（永远不响应）。
        详见 `core/i18n/useTranslator.tsx` 的说明。
      */}
      <LocaleProvider>
        {/*
          SessionProvider 持有当前演示身份与它的能力快照。门禁默认给全量能力，
          因此界面与门禁落地前逐像素相同；切换到只读身份才隐藏写入口。
          详见 `core/session/SessionProvider.tsx`。
        */}
        <SessionProvider>
          <AstryxProvider>
            <App />
          </AstryxProvider>
        </SessionProvider>
      </LocaleProvider>
    </ReactFrameworkProvider>
  </React.StrictMode>,
);
