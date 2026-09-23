import { expect, test } from "@playwright/test";

test("rebuilds a real recording from the button and automatically loads new evidence", async ({
  page,
}, testInfo) => {
  test.skip(
    !process.env.EVIDENCE_REBUILD_LIVE,
    "explicit opt-in: creates a new local evidence bundle",
  );
  test.setTimeout(240_000);
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  // Force only the initial stale presentation; rebuilding and all results use the real API.
  let firstCatalog = true;
  let firstDetail = true;
  await page.route("**/api/datasets", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    if (firstCatalog) {
      firstCatalog = false;
      body.datasets.find(
        (d) => d.dataset_id === "lilocbench_dynamics_0",
      ).capabilities.recordings = "stale";
    }
    await route.fulfill({ response, json: body });
  });
  await page.route("**/api/investigations/lilocbench_dynamics_0", (route) => {
    if (firstDetail) {
      firstDetail = false;
      return route.fulfill({
        status: 409,
        json: { detail: "Evidence is stale" },
      });
    }
    return route.continue();
  });
  await page.addInitScript(() => {
    localStorage.setItem("workbench.dataset", "lilocbench_dynamics_0");
    localStorage.setItem("workbench.view", "recordings");
  });
  await page.goto("/");
  const button = page.getByRole("button", {
    name: "Rebuild evidence",
    exact: true,
  });
  await expect(button).toBeEnabled({ timeout: 30_000 });
  const post = page.waitForResponse(
    (r) =>
      r.url().endsWith("/lilocbench_dynamics_0/preparation") &&
      r.request().method() === "POST",
  );
  const refreshedCatalog = page.waitForResponse(
    (r) => r.url().endsWith("/api/datasets") && r.ok(),
    { timeout: 210_000 },
  );
  await button.click();
  expect((await post).status()).toBe(202);
  await expect(page.getByText(/Results will load automatically/)).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Rebuilding evidence…", exact: true }),
  ).toBeDisabled();
  const metadata = await page.waitForResponse(
    (r) =>
      r.url().endsWith("/api/investigations/lilocbench_dynamics_0") && r.ok(),
    { timeout: 210_000 },
  );
  const body = await metadata.json();
  expect(body.incident_count).toBeGreaterThan(0);
  await expect(
    page.getByRole("region", { name: "Detected incidents" }),
  ).toBeVisible();
  await expect(
    page.getByText("Last rebuild completed.", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText(/prepare_investigations.py/)).toHaveCount(0);
  await page
    .getByRole("region", { name: "Detected incidents" })
    .getByRole("button")
    .filter({ hasText: "65.781" })
    .click();
  await expect(
    page.getByRole("article", { name: "Incident explanation" }),
  ).toContainText("13 commands");
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  const catalog = await (await refreshedCatalog).json();
  expect(
    catalog.datasets.find((d) => d.dataset_id === "lilocbench_dynamics_0")
      .capabilities.recordings,
  ).toBe("ready");
  await expect(page.getByRole("tab", { name: /Recording/ })).not.toContainText(
    "Needs refresh",
  );
  expect(
    (await page.locator(".evidence-preparation").boundingBox()).height,
  ).toBeLessThan(180);
  await page.screenshot({
    path: testInfo.outputPath("rebuilt-evidence-mobile.png"),
    fullPage: true,
  });
  await page.unrouteAll({ behavior: "wait" });
  expect(errors).toEqual([]);
});
