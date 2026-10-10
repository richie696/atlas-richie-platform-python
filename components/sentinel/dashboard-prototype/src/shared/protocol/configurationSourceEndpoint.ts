/** URL syntax shared by configuration-source forms and runtime wire schemas. */
export function isSupportedConfigurationSourceEndpoint(value: string): boolean {
  const candidate = value;
  if (
    !candidate ||
    /[\p{White_Space}\u001c-\u001f\ufeff\\]/u.test(candidate) ||
    candidate.includes("?") ||
    candidate.includes("#")
  ) {
    return false;
  }

  try {
    const url = new URL(candidate);
    if (
      !["http:", "https:"].includes(url.protocol) ||
      !url.hostname ||
      url.username ||
      url.password ||
      url.search ||
      url.hash
    ) {
      return false;
    }

    const authority = /^(?:https?):\/\/([^/?#\\]*)/i.exec(candidate)?.[1];
    if (!authority || authority.includes("@")) return false;
    const bracketedHost = authority.startsWith("[");
    const hostname = bracketedHost
      ? authority.slice(1, authority.indexOf("]"))
      : authority.slice(
          0,
          authority.lastIndexOf(":") > -1 ? authority.lastIndexOf(":") : undefined,
        );
    if (!hostname || hostname.includes("%")) return false;
    if (bracketedHost) return true;

    const numericHost = hostname.endsWith(".") ? hostname.slice(0, -1) : hostname;
    const lastLabel = numericHost.split(".").at(-1) ?? "";
    const endsInNumber = /^[0-9]+$/.test(lastLabel) || /^0x[0-9a-f]*$/i.test(lastLabel);
    if (endsInNumber && hostname.toLowerCase() !== url.hostname.toLowerCase()) return false;
    const canonicalHostname = url.hostname.endsWith(".") ? url.hostname.slice(0, -1) : url.hostname;
    const labels = canonicalHostname.split(".");
    return (
      canonicalHostname.length <= 253 &&
      labels.every((label) => label.length <= 63 && /^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$/.test(label))
    );
  } catch {
    return false;
  }
}
