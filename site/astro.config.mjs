// Starlight site for code-copilot-team (#214 Phase 4).
//
// Content is NOT kept here: `node build-content.mjs` stages the repository's
// own documentation into src/content/docs (gitignored) from the same registry
// the Studio's Learn tab reads, so the site cannot describe a different set of
// documents than the repository does.
import { defineConfig } from "astro/config";
import starlight from "@astrojs/starlight";
import { readFileSync } from "node:fs";

const sidebar = JSON.parse(readFileSync(new URL("./sidebar.generated.json", import.meta.url), "utf8"));
const registry = JSON.parse(
  readFileSync(new URL("../scripts/session_analytics/config_data/learn-sections.json", import.meta.url), "utf8"),
);

// A project site lives under /<repo>/ on github.io; an override lets a fork or
// a custom domain build the same tree at the root.
const repoName = registry.repo_url.split("/").pop();
const base = process.env.SITE_BASE ?? `/${repoName}`;
const site = process.env.SITE_URL ?? `https://${registry.repo_url.split("/")[3]}.github.io`;

export default defineConfig({
  site,
  base,
  outDir: "./dist",
  trailingSlash: "always",
  integrations: [
    starlight({
      title: "Code Copilot Team",
      description:
        "An enforceable harness for AI-assisted coding: your rules, your workflow and your safety rails, applied the same way by every coding agent you use.",
      social: [{ icon: "github", label: "GitHub", href: registry.repo_url }],
      editLink: { baseUrl: `${registry.repo_url}/edit/${registry.repo_branch}/` },
      lastUpdated: true,
      sidebar,
      customCss: ["./src/styles/banner.css"],
      components: { Banner: "./src/components/ReleaseBanner.astro" },
    }),
  ],
});
