import assert from "node:assert/strict";
import { test } from "node:test";
import { LOCALES } from "../../src/app/i18n/locales.ts";
import { formatLocaleNumber } from "../../src/shared/presentation/formatLocaleNumber.ts";
import {
  formatUtcDateTime,
  formatUtcInstant,
} from "../../src/shared/presentation/utcDateTime.ts";
import {
  getSystemTimeZone,
  setSystemTimeZone,
} from "../../src/shared/presentation/systemTimeZone.ts";

test("F5.2 Intl number formatting applies grouping and fraction policy in every supported locale", () => {
  const value = 1_234_567.891;
  const formatted = LOCALES.map((locale) =>
    formatLocaleNumber(value, locale, { maximumFractionDigits: 2 }),
  );

  assert.deepEqual(formatted, ["1,234,567.89", "1,234,567.89", "1,234,567.89"]);
  assert.equal(
    formatLocaleNumber(Number.MAX_SAFE_INTEGER, "en-US"),
    "9,007,199,254,740,991",
  );
  assert.equal(value, 1_234_567.891);
});

test("F5.2 rendering follows the configured display zone and never shifts the wire instant across a date boundary", () => {
  const instant = Date.UTC(2026, 0, 1, 0, 30);
  const style = { dateStyle: "full", timeStyle: "short" };
  const original = getSystemTimeZone();
  try {
    for (const zone of ["UTC", "Asia/Shanghai", "America/New_York"]) {
      setSystemTimeZone(zone);
      for (const locale of LOCALES) {
        // The reference is Intl rendering the same instant in the same zone. Equal output
        // means the wire instant was not shifted, only expressed in the configured zone.
        const expected = new Intl.DateTimeFormat(locale, { ...style, timeZone: zone }).format(
          instant,
        );
        assert.equal(
          formatUtcInstant(instant, locale, style),
          expected,
          `${locale} in ${zone}`,
        );
        const marker = new Intl.DateTimeFormat(locale, {
          timeZone: zone,
          timeZoneName: "shortOffset",
        })
          .formatToParts(instant)
          .find((part) => part.type === "timeZoneName")?.value;
        assert.equal(
          formatUtcDateTime(instant, locale, style),
          `${expected} ${marker}`,
          `${locale} in ${zone}`,
        );
      }
    }
    // The marker identifies the configured zone, never the host's own zone.
    setSystemTimeZone("UTC");
    assert.match(
      formatUtcDateTime(instant, "en-US", style),
      / GMT\+0$/,
      "a UTC display zone is marked as GMT+0, not as a local offset",
    );
    setSystemTimeZone("Asia/Shanghai");
    assert.match(formatUtcDateTime(instant, "en-US", style), / GMT\+8$/);
  } finally {
    setSystemTimeZone(original);
  }
  assert.equal(new Date(instant).toISOString(), "2026-01-01T00:30:00.000Z");
});
