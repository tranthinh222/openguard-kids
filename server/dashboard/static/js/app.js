import { initAuthenticatedShell, showGlobalError } from "./common.js";
import { initRegisterPage } from "./register.js";
import { initLoginPage } from "./login.js";
import { initDashboardPage } from "./dashboard.js";
import { initChildrenPage } from "./children.js";
import { initChildCreatePage } from "./child-create.js";
import { initChildDetailPage } from "./child-detail.js";
import { initPoliciesPage, initPolicyDetailPage } from "./policies.js";
import { initRequestsPage } from "./requests.js";

async function main() {
  const page = document.body.dataset.page;

  if (page === "login") {
    await initLoginPage();
    return;
  }

  if (page === "register") {
    await initRegisterPage();
    return;
  }

  const session = await initAuthenticatedShell();
  if (!session) return;

  switch (page) {
    case "dashboard":
      await initDashboardPage();
      break;
    case "children":
      await initChildrenPage();
      break;
    case "child-create":
      initChildCreatePage();
      break;
    case "child-detail":
      await initChildDetailPage();
      break;
    case "policies":
      await initPoliciesPage();
      break;
    case "policy-detail":
      await initPolicyDetailPage();
      break;
    case "requests":
      await initRequestsPage();
      break;
    default:
      break;
  }
}

main().catch((error) => {
  console.error(error);
  showGlobalError(error.message || "Có lỗi xảy ra khi tải dữ liệu.");
});
