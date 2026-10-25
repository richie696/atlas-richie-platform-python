/** Install one explicit mock identity before a protected application route loads. */
export async function gotoMockSession(page, url, role = "admin") {
  const { identifier } = await page.send("Page.addScriptToEvaluateOnNewDocument", {
    source: `if (location.origin !== "null") localStorage.setItem("sentinel.mock.role", ${JSON.stringify(role)})`,
  });
  try {
    await page.goto(url);
  } finally {
    await page.send("Page.removeScriptToEvaluateOnNewDocument", { identifier });
  }
  await page.waitFor(`!!document.querySelector(".main-nav")`, {
    label: `mock ${role} session`,
  });
}

export const gotoMockAdministrator = (page, url) => gotoMockSession(page, url, "admin");
