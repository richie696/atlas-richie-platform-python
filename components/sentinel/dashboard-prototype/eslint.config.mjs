import babelParser from "@babel/eslint-parser";
import reactHooks from "eslint-plugin-react-hooks";

/**
 * React 官方 recommended 门禁。类型检查仍由 tsc 负责，不混用第二套 TypeScript 编译器。
 * 当前 TS 7 超出 typescript-eslint parser 的 peer 范围，因此沿用 Vite React
 * 已使用的 Babel 语法链。此配置不是类型感知 lint，不声称覆盖 unsafe/promises 规则。
 */
export default [
  {
    files: ["src/**/*.{ts,tsx}", "tests/e2e/probes/**/*.{ts,tsx}"],
    languageOptions: {
      parser: babelParser,
      parserOptions: {
        requireConfigFile: false,
        babelOptions: {
          babelrc: false,
          configFile: false,
          parserOpts: { plugins: ["typescript", "jsx"] },
        },
      },
    },
    plugins: { "react-hooks": reactHooks },
    rules: {
      ...reactHooks.configs.flat.recommended.rules,
      "react-hooks/exhaustive-deps": "error",
    },
  },
];
