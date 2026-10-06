import React from "react";
import { createRoot } from "react-dom/client";
import { ReactFrameworkProvider } from "@richie696/react-framework-react";
import { App } from "./App";
import { AstryxProvider } from "./app/providers/AstryxProvider";
import { LocaleProvider } from "./core/i18n/useTranslator";
import "./styles.css";

const frameworkOptions = Object.freeze({
  baseUrl: window.location.origin,
  showLoading: false,
});

/**
 * 首屏语言在**挂载前**确定，避免挂载后再切导致的语言闪烁。
 * 语言选择是本机界面偏好，不进 URL；刷新后回落到默认语言是可接受的，
 * 正式实现应从 `StorageAdapter` 读取。
 */
const storedLocale = (() => {
  try {
    return window.localStorage.getItem("sentinel.locale") ?? "";
  } catch {
    // 隐私模式下 localStorage 可能抛异常；语言回落到默认即可，不阻断渲染。
    return "";
  }
})();

const initialLocale = storedLocale;

const rootElement = document.getElementById("root");

if (!rootElement) {
  throw new Error("Dashboard root element is missing.");
}

createRoot(rootElement).render(
  <React.StrictMode>
    <ReactFrameworkProvider options={frameworkOptions}>
      <LocaleProvider locale={initialLocale}>
        <AstryxProvider>
          <App />
        </AstryxProvider>
      </LocaleProvider>
    </ReactFrameworkProvider>
  </React.StrictMode>,
);
