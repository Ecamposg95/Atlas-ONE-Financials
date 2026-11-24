import { defineRailway, github, project, service } from "railway/iac";
// This repository manages only its own resources in the environment. Other
// repositories export their own partial name.
// See https://docs.railway.com/infrastructure-as-code#multi-repo-projects
export const partial = "ARCA";
export default defineRailway(() => {
  const ARCA = service("ARCA", {
    source: github("Ecamposg95/Atlas-ONE-Financials", { branch: "main", checkSuites: false }),
    build: { buildEnvironment: "V3", builder: "RAILPACK" },
    healthcheck: "/api/health",
    healthcheckTimeout: 300,
    replicas: { "us-west2": 1 },
    networking: { privateNetworkEndpoint: "arca" },
  });

  return project("Atlas ONE Financials", {
    variables: { managed: false },
    resources: [ARCA],
  });
});
