import path from "node:path";
import {fileURLToPath} from "node:url";

import {describe, expect, it} from "vitest";

import config from "./playwright.config";

const webRoot = path.dirname(fileURLToPath(import.meta.url));
const repositoryRoot = path.resolve(webRoot, "../..");

describe("Playwright web servers", () => {
  it("starts the API with the cross-platform Python command from the repository root", () => {
    const webServers = Array.isArray(config.webServer) ? config.webServer : [config.webServer];
    const apiServer = webServers[0];

    expect(apiServer).toBeDefined();
    expect(apiServer?.command).toBe("python scripts/browser_test_api.py");
    expect(apiServer?.cwd).toBe(repositoryRoot);
    expect(apiServer?.env?.PYTHONPATH).toBe(
      [
        path.join(repositoryRoot, "apps/api/src"),
        path.join(repositoryRoot, "sdk/python/src"),
      ].join(path.delimiter),
    );
  });
});
