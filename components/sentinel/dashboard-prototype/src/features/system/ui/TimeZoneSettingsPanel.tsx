import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { ActionButton } from "../../../shared/ui/ActionButton";
import { Panel } from "../../../shared/ui/Panel";
import { Select } from "../../../shared/ui/Select";
import { setSystemTimeZone } from "../../../shared/presentation/systemTimeZone";
import type { SystemSettingsPort } from "../api/systemSettingsPort";
import settingsStyles from "./TimeZoneSettingsPanel.module.scss";
import { scopedClasses } from "../../../shared/ui/styles/scopedClasses";

const styleModules = [settingsStyles] as const;
const fallbackZones = [
  "America/Los_Angeles",
  "America/New_York",
  "Europe/London",
  "Europe/Paris",
  "Asia/Tokyo",
  "Asia/Shanghai",
  "Asia/Singapore",
  "Australia/Sydney",
  "Pacific/Auckland",
];

function supportedZones(): readonly string[] {
  const api = Intl as typeof Intl & { supportedValuesOf?: (key: "timeZone") => string[] };
  return api.supportedValuesOf?.("timeZone") ?? fallbackZones;
}

function offsetMinutes(timeZone: string, at: Date): number {
  const raw =
    new Intl.DateTimeFormat("en", { timeZone, timeZoneName: "longOffset" })
      .formatToParts(at)
      .find(({ type }) => type === "timeZoneName")?.value ?? "GMT";
  const match = /GMT([+-])(\d{1,2}):(\d{2})/.exec(raw);
  if (!match) return 0;
  const magnitude = Number(match[2]) * 60 + Number(match[3]);
  return match[1] === "-" ? -magnitude : magnitude;
}

function offsetLabel(minutes: number): string {
  const sign = minutes < 0 ? "-" : "+";
  const absolute = Math.abs(minutes);
  const hours = Math.floor(absolute / 60)
    .toString()
    .padStart(2, "0");
  const remainder = (absolute % 60).toString().padStart(2, "0");
  return `(${sign}${hours}:${remainder})`;
}

function cityName(timeZone: string): string {
  return timeZone.split("/").at(-1)?.replaceAll("_", " ") ?? timeZone;
}

export function TimeZoneSettingsPanel({
  settings,
  canManage,
}: {
  readonly settings: SystemSettingsPort;
  readonly canManage: boolean;
}) {
  const { t } = useTranslation();
  const [timeZone, setTimeZone] = useState("Asia/Shanghai");
  const [savedTimeZone, setSavedTimeZone] = useState("Asia/Shanghai");
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState(false);
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    void settings
      .read(controller.signal)
      .then((snapshot) => {
        setTimeZone(snapshot.timeZone);
        setSavedTimeZone(snapshot.timeZone);
        setSystemTimeZone(snapshot.timeZone);
        setError(false);
      })
      .catch(() => setError(true))
      .finally(() => setBusy(false));
    return () => controller.abort();
  }, [settings]);
  const allZones = useMemo(() => supportedZones(), []);
  const zones = useMemo(() => {
    const now = new Date();
    return allZones
      .map((zone) => ({
        value: zone,
        offset: offsetMinutes(zone, now),
        city: cityName(zone),
      }))
      .sort(
        (left, right) =>
          left.offset - right.offset ||
          left.city.localeCompare(right.city, "en") ||
          left.value.localeCompare(right.value),
      )
      .map(({ value, offset, city }) => ({
        value,
        label: `${offsetLabel(offset)} ${city} (${value})`,
      }));
  }, [allZones]);
  const selectedOption = zones.find(({ value }) => value === timeZone);
  const options = selectedOption
    ? zones
    : [
        {
          value: timeZone,
          label: `${offsetLabel(offsetMinutes(timeZone, new Date()))} ${cityName(timeZone)} (${timeZone})`,
        },
        ...zones,
      ];
  const save = async () => {
    setBusy(true);
    setError(false);
    setSaved(false);
    const controller = new AbortController();
    try {
      const snapshot = await settings.updateTimeZone(timeZone, controller.signal);
      setTimeZone(snapshot.timeZone);
      setSavedTimeZone(snapshot.timeZone);
      setSystemTimeZone(snapshot.timeZone);
      setSaved(true);
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel title={t("system.timeZone.title")} subtitle={t("system.timeZone.description")}>
      <div className={scopedClasses(styleModules, "body")}>
        <Select
          label={t("system.timeZone.zone")}
          value={timeZone}
          options={options}
          onChange={setTimeZone}
          disabled={busy || !canManage}
        />
        <p className={scopedClasses(styleModules, "hint")}>
          {t("system.timeZone.hint", { zone: savedTimeZone })}
        </p>
        {error && (
          <p role="alert" className={scopedClasses(styleModules, "error")}>
            {t("system.timeZone.error")}
          </p>
        )}
        {saved && (
          <p role="status" className={scopedClasses(styleModules, "saved")}>
            {t("system.timeZone.saved")}
          </p>
        )}
        {canManage && (
          <div className={scopedClasses(styleModules, "actions")}>
            <ActionButton
              type="button"
              disabled={busy || timeZone === savedTimeZone}
              onClick={() => void save()}
            >
              {t("system.timeZone.save")}
            </ActionButton>
          </div>
        )}
      </div>
    </Panel>
  );
}
