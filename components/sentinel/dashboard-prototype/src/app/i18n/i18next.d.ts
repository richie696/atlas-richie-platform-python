import "i18next";
import type { TranslationResources } from "./resourceKeys";

declare module "i18next" {
  interface CustomTypeOptions {
    defaultNS: "translation";
    resources: TranslationResources;
    keySeparator: false;
    nsSeparator: false;
    returnNull: false;
    strictKeyChecks: true;
  }
}
