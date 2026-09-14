import React from "react";
import { createRoot } from "react-dom/client";
import { ReactFrameworkProvider } from "@richie696/react-framework-react";
import { App } from "./App.jsx";
import "./styles.css";

const frameworkOptions = Object.freeze({
  baseUrl: window.location.origin,
  showLoading: false,
});

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <ReactFrameworkProvider options={frameworkOptions}>
      <App />
    </ReactFrameworkProvider>
  </React.StrictMode>,
);
