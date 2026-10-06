import type { ReactNode } from "react";

/** Page heading block with optional contextual action or status. */
export function Intro({ eyebrow, title, description, aside = null }: { eyebrow: ReactNode; title: ReactNode; description: ReactNode; aside?: ReactNode }) {
  return <div className="intro"><div><span className="eyebrow">{eyebrow}</span><h1>{title}</h1><p>{description}</p></div>{aside && <div className="intro-aside">{aside}</div>}</div>;
}
