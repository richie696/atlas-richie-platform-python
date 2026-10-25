import introStyles from "./Intro.module.scss";
import { scopedClasses } from "./styles/scopedClasses";
import type { ReactNode } from "react";

const styleModules = [introStyles] as const;

/** Page heading block with optional contextual action or status. */
export function Intro({
  eyebrow,
  title,
  description,
  aside = null,
}: {
  eyebrow: ReactNode;
  title: ReactNode;
  description: ReactNode;
  aside?: ReactNode;
}) {
  return (
    <div className={scopedClasses(styleModules, "intro")}>
      <div>
        <span className={scopedClasses(styleModules, "eyebrow")}>{eyebrow}</span>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {aside && <div className={scopedClasses(styleModules, "intro-aside")}>{aside}</div>}
    </div>
  );
}
