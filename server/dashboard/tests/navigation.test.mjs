import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const dashboard = path.resolve(here, "..");
const read = (relative) =>
  fs.readFileSync(path.join(dashboard, relative), "utf8");

test("Week 02 gives Policies and Requests first-class navigation routes", () => {
  const base = read("templates/base.html");
  assert.match(base, /href="\/policies"/);
  assert.match(base, />Chính sách<\/a/);
  assert.match(base, /href="\/requests"/);
  assert.match(base, />Yêu cầu<\/a/);
  assert.doesNotMatch(base, /\/children\?view=policies/);
  assert.doesNotMatch(base, /\/children\?view=requests/);
  assert.match(base, /Sẽ triển khai ở Week 03/);
  assert.match(base, /app\.js\?v=w02-ia-fix1/);
});

test("Children detail keeps child/device/enrollment role and links to workspaces", () => {
  const detail = read("templates/children/detail.html");
  assert.doesNotMatch(detail, /id="policy-section"/);
  assert.doesNotMatch(detail, /id="requests-section"/);
  assert.match(detail, /id="child-policy-link"/);
  assert.match(detail, /href="\/policies\/\{\{ child_id \}\}"/);
  assert.match(detail, /id="child-requests-link"/);
  assert.match(detail, /href="\/requests\?child_id=\{\{ child_id \}\}"/);
});

test("Policy workspace owns policy editor and weekly schedule", () => {
  const detail = read("templates/policies/detail.html");
  const js = read("static/js/policies.js");
  assert.match(detail, /id="weekday-minutes"/);
  assert.match(detail, /id="schedule-grid"/);
  assert.match(js, /initPolicyDetailPage/);
  assert.match(js, /336/);
  assert.match(js, /\/api\/v1\/children\/\$\{encodedId\}\/policy/);
});

test("Requests workspace owns centralized request queue", () => {
  const template = read("templates/requests/index.html");
  const js = read("static/js/requests.js");
  assert.match(template, /id="request-child-filter"/);
  assert.match(template, /id="request-status-filter"/);
  assert.match(js, /initRequestsPage/);
  assert.match(js, /\/approve/);
  assert.match(js, /\/reject/);
});

test("Week 01 enrollment behavior remains in Child Detail", () => {
  const js = read("static/js/child-detail.js");
  assert.match(js, /copyEnrollmentCode/);
  assert.match(js, /document\.execCommand\("copy"\)/);
  assert.match(js, /activeEnrollmentId/);
  assert.match(js, /Ghép đôi thành công!/);
  assert.match(js, /Mã ghép đôi đã hết hạn\./);
});

test("Policies and Requests replace infinite loading with visible error states", () => {
  const policies = read("static/js/policies.js");
  const requests = read("static/js/requests.js");
  const live = read("static/js/live-refresh.js");
  assert.match(policies, /renderPolicyOverviewError/);
  assert.match(requests, /renderRequestsError/);
  assert.match(live, /onError/);
});
