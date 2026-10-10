/** Preserve user IDs, classes/styles and reference relationships; strip only known runtime noise. */
export function normalizeDom(html) {
  const cleaned = html
    .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, "")
    .replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, "")
    .replace(/\sdata-backend-node-id="[^"]*"/g, "")
    .replace(/\sdata-pressable-container="[^"]*"/g, "");
  const ids = new Map();
  return cleaned
    .replace(/_r_[a-zA-Z0-9]+_|_react_id_[0-9]+_/g, value => {
      if (!ids.has(value)) ids.set(value, `_react_id_${ids.size}_`);
      return ids.get(value);
    })
    .replace(/\s+/g, " ").replace(/> </g, "><").trim();
}

/**
 * Historical captures already destroyed id attributes and SVG references.
 * Use their original policy symmetrically, explicitly reporting this weaker
 * comparison. Never use this policy for new raw captures or ARIA assertions.
 */
export function normalizeLegacyDom(html) {
  return normalizeDom(html
    .replace(/\sid="[^"]*"/g, ' id="_"')
    .replace(/url\(#[^)]*\)/g, "url(#_)")
    .replace(/\sclip-path="[^"]*"/g, ' clip-path="url(#_)"'));
}
