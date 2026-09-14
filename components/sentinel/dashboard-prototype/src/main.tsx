import React from "react";
import { createRoot } from "react-dom/client";
import { ReactFrameworkProvider } from "@richie696/react-framework-react";
import { App } from "./App";
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
      <App />
    </ReactFrameworkProvider>
  </React.StrictMode>,
);
