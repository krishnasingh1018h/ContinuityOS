const path = require("node:path");
const { test, expect } = require("@playwright/test");

const password = "browser-test-password-2026";

async function signUp(page, email) {
  await page.goto("/");
  await page.getByRole("button", { name: "Create account" }).click();
  await page.locator("#auth-email").fill(email);
  await page.locator("#auth-password").fill(password);
  await page.locator("#auth-submit").click();
  await expect(page.locator("#workspace")).toBeVisible();
}

async function signIn(page, email) {
  await page.goto("/");
  await expect(page.locator("#auth-screen")).toBeVisible();
  await page.locator('[data-auth-mode="login"]').click();
  await page.locator("#auth-email").fill(email);
  await page.locator("#auth-password").fill(password);
  await page.locator("#auth-submit").click();
  await expect(page.locator("#workspace")).toBeVisible();
}

async function signOut(page) {
  await page.locator("#logout").click();
  await expect(page.locator("#auth-screen")).toBeVisible();
}

async function uploadSource(page, filename, sensitivity) {
  await page.locator(".nav-item[data-view='sources']").click();
  if (sensitivity === "restricted") {
    await page.locator("#source-sensitivity").selectOption("restricted");
  }
  await page.locator("#source-file").setInputFiles(
    path.join(__dirname, "fixtures", filename),
  );
  await page.getByRole("button", { name: "Upload and extract" }).click();
  await expect(page.locator("#source-list")).toContainText(filename);
}

test("owner approves a cited handover and incoming lead receives only cleared claims", async ({ page }) => {
  const suffix = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const ownerEmail = `e2e-owner-${suffix}@example.test`;
  const incomingEmail = `e2e-incoming-${suffix}@example.test`;
  const publicClaim = "Decision: E2E handover uses the verified field-test configuration.";
  const restrictedMarker = "PRIVATE_HANDOVER_SECRET";

  await signUp(page, ownerEmail);
  await page.locator("#new-project-name").fill("Browser handover");
  await page.getByRole("button", { name: "Create project" }).click();
  await expect(page.locator("#project-name")).toHaveText("Browser handover");

  for (const [theme, sidebarColor] of [
    ["clean-light", "rgb(237, 243, 239)"],
    ["dark", "rgb(12, 18, 23)"],
    ["editorial", "rgb(48, 39, 31)"],
  ]) {
    await page.locator("#theme-switch").selectOption(theme);
    await expect(page.locator("#workspace")).toHaveAttribute("data-theme", theme);
    await expect(page.locator(".sidebar")).toHaveCSS("background-color", sidebarColor);
  }
  await page.reload();
  await expect(page.locator("#workspace")).toHaveAttribute("data-theme", "editorial");
  await page.setViewportSize({ width: 390, height: 844 });
  for (const theme of ["clean-light", "dark", "editorial"]) {
    await page.locator("#theme-switch").selectOption(theme);
    await expect.poll(() =>
      page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth),
    ).toBe(true);
  }
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.locator("#theme-switch").selectOption("clean-light");

  await uploadSource(page, "public_decision.md", "project");
  await uploadSource(page, "restricted_decision.md", "restricted");

  await page.locator(".nav-item[data-view='dashboard']").click();
  await page.locator("#reconstruct").click();
  await expect(page.locator("#toast")).toContainText("reconstruction proposed 2 claim(s)");

  await page.locator(".nav-item[data-view='conflicts']").click();
  await page.locator("#conflict-first").selectOption({ label: publicClaim });
  await page.locator("#conflict-second").selectOption({
    label: "Decision: PRIVATE_HANDOVER_SECRET remains restricted to the review team.",
  });
  await page.getByRole("button", { name: "Record conflict" }).click();
  const conflict = page.locator("#view-root article").filter({ hasText: "PRIVATE_HANDOVER_SECRET" });
  await conflict.locator('input[id^="rationale-"]').fill("The statements cover separate clearance scopes.");
  await conflict.getByRole("button", { name: "Retain as ambiguity" }).click();
  await expect(page.locator("#toast")).toContainText("Conflict decision recorded");

  await page.locator(".nav-item[data-view='claims']").click();
  for (const claimText of [
    publicClaim,
    "Decision: PRIVATE_HANDOVER_SECRET remains restricted to the review team.",
  ]) {
    const claim = page.locator(".claim-row").filter({ hasText: claimText });
    await claim.getByRole("button", { name: "Accept" }).click();
    await expect(claim.locator(".claim-meta")).toContainText("accepted");
  }

  await page.locator(".nav-item[data-view='handover']").click();
  page.once("dialog", (dialog) => dialog.accept());
  await page.locator("#approve-handover").click();
  await expect(page.getByRole("heading", { name: "Your recipient view · version 1" })).toBeVisible();

  await signOut(page);
  await signUp(page, incomingEmail);
  await signOut(page);
  await signIn(page, ownerEmail);
  await page.locator(".nav-item[data-view='team']").click();
  await page.locator("#member-email").fill(incomingEmail);
  await page.locator("#member-role").selectOption("incoming_lead");
  await page.getByRole("button", { name: "Save project role" }).click();
  await expect(page.locator("#toast")).toContainText("Project membership updated");

  await signOut(page);
  await signIn(page, incomingEmail);
  await page.locator(".nav-item[data-view='handover']").click();
  await expect(page.getByRole("heading", { name: "Your recipient view · version 1" })).toBeVisible();
  await expect(page.locator("#view-root")).toContainText(publicClaim);
  await expect(page.locator("#view-root")).not.toContainText(restrictedMarker);
  await expect(page.locator(".redaction-box")).toContainText(
    "1 claim(s) and 1 evidence item(s) withheld",
  );

  await page.locator("#ack-note").fill("Received the cleared project handover.");
  await page.getByRole("button", { name: "Acknowledge receipt" }).click();
  await expect(page.locator("#toast")).toContainText(
    "Receipt acknowledged. This does not imply agreement with every claim.",
  );
  await expect(page.locator("#ack-note")).toHaveValue("");
});
