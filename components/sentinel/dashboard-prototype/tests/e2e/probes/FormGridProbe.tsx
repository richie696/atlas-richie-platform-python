import { useState } from "react";
import { AstryxProvider } from "../../../src/app/providers/AstryxProvider";
import { FormGrid, FormGridFullRow } from "../../../src/shared/ui/FormGrid";
import { TextField } from "../../../src/shared/ui/TextField";
import { NumberField } from "../../../src/shared/ui/NumberField";
import { Select } from "../../../src/shared/ui/Select";
import { CheckboxField } from "../../../src/shared/ui/CheckboxField";

const HELP = {
  zh: "统计窗口分成多个样本后每段必须至少为一毫秒；这是用于验证长帮助文本换行的示例说明。",
  en: "The statistical window must divide into samples of at least one millisecond each. This longer description exercises wrapped help text without fixed label heights.",
  ja: "統計ウィンドウを複数のサンプルに分割したとき、各区間は最低一ミリ秒必要です。長い説明が折り返されても入力欄の位置を揃えます。",
} as const;

/** Actual shared controls in a controlled container; no cloned markup or layout measurements in render. */
export function FormGridProbe() {
  const [locale, setLocale] = useState<keyof typeof HELP>("zh");
  const [narrow, setNarrow] = useState(false);
  const [error, setError] = useState(false);
  const [name, setName] = useState("demo");
  const [quota, setQuota] = useState("10");
  const [fallback, setFallback] = useState(true);
  return (
    <AstryxProvider>
      <section style={{ padding: 24 }}>
        <button data-action="error" onClick={() => setError((value) => !value)}>
          status
        </button>
        <button data-action="width" onClick={() => setNarrow((value) => !value)}>
          container
        </button>
        {Object.keys(HELP).map((key) => (
          <button
            key={key}
            data-locale={key}
            onClick={() => {
              if (key === "zh" || key === "en" || key === "ja") setLocale(key);
            }}
          >
            {key}
          </button>
        ))}
        <div data-probe-container style={{ width: narrow ? 260 : 560, maxWidth: "100%" }}>
          <FormGrid>
            <TextField label="Account" hint="Short hint" value={name} onChange={setName} />
            <NumberField
              label="Quota"
              hint={HELP[locale]}
              value={quota}
              onChange={setQuota}
              allowEmpty
              step={null}
              error={
                error
                  ? "Enter a finite positive quota. This detached error must not shift other controls in the row."
                  : undefined
              }
            />
            <Select
              label="Mode"
              value="qps"
              options={[{ value: "qps", label: "QPS" }]}
              onChange={() => undefined}
            />
            <TextField
              label="Additional explanation with a longer label"
              value="Example"
              onChange={() => undefined}
            />
            <FormGridFullRow>
              <TextField
                label="Full-row field"
                hint={HELP[locale]}
                value="example"
                onChange={() => undefined}
              />
            </FormGridFullRow>
          </FormGrid>
        </div>
        <CheckboxField
          label="Allow fallback"
          checked={fallback}
          onChange={setFallback}
          hint={HELP[locale]}
        />
        <output>{JSON.stringify({ narrow, error, locale, name, quota, fallback })}</output>
      </section>
    </AstryxProvider>
  );
}
