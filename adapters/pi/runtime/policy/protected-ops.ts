/**
 * Package-install and network command classifiers (T5.3, FR-009).
 *
 * Pure matchers used by the exec-tool permission path when
 * `security.allow_package_install` is false or `security.deny_network` is true.
 * A command is classified as package-install only by manager BINARY + install
 * VERB (never the manager alone, so `npm run build` / `cargo build` / `go build`
 * are not install), or as network only by an enumerated network-CLI binary or a
 * network git subcommand.
 *
 * Boundary (spec P5, design-t53-protected.md): `deny_network` is a command-NAME
 * denylist, NOT a sandbox — a program that opens a socket without a known
 * network binary (e.g. `python fetch.py`) is not caught. Callers report this.
 */

interface PackageManagerSpec {
  verbs: Set<string>;
  bareInstalls: boolean; // bare `<mgr>` (no non-flag arg) == install
}

// Manager -> the first-non-flag argument values that mean "install/fetch".
const PACKAGE_MANAGERS: Record<string, PackageManagerSpec> = {
  npm: {
    verbs: new Set(["install", "i", "ci", "add", "update"]),
    bareInstalls: false,
  },
  yarn: { verbs: new Set(["add", "install"]), bareInstalls: true },
  pnpm: {
    verbs: new Set(["add", "install", "i", "update"]),
    bareInstalls: false,
  },
  pip: { verbs: new Set(["install"]), bareInstalls: false },
  pip3: { verbs: new Set(["install"]), bareInstalls: false },
  poetry: { verbs: new Set(["add", "install"]), bareInstalls: false },
  cargo: { verbs: new Set(["install", "add"]), bareInstalls: false },
  go: { verbs: new Set(["get", "install"]), bareInstalls: false },
  gem: { verbs: new Set(["install"]), bareInstalls: false },
  apt: { verbs: new Set(["install"]), bareInstalls: false },
  "apt-get": { verbs: new Set(["install"]), bareInstalls: false },
  brew: { verbs: new Set(["install"]), bareInstalls: false },
  pipx: { verbs: new Set(["install"]), bareInstalls: false },
  bundle: { verbs: new Set(["install", "add"]), bareInstalls: true },
  composer: { verbs: new Set(["install", "require"]), bareInstalls: false },
};

// Download-and-run tools: fetch a package AND use the network (decision A).
const DLX_TOOLS = new Set(["npx", "bunx", "uvx"]);

const NETWORK_BINS = new Set([
  "curl",
  "wget",
  "nc",
  "ncat",
  "netcat",
  "ssh",
  "scp",
  "sftp",
  "telnet",
  "ftp",
  "rsync",
]);
const NETWORK_GIT_SUBCMDS = new Set([
  "clone",
  "fetch",
  "pull",
  "push",
  "remote",
]);

// Install-ish verbs after an UNKNOWN leading binary -> ambiguous (fail_closed).
const AMBIGUOUS_INSTALL_VERBS = new Set(["install", "add", "get", "require"]);

// sudo flags that consume the following token as a value.
const SUDO_VALUE_FLAGS = new Set([
  "-u",
  "-g",
  "-p",
  "-h",
  "-C",
  "-r",
  "-t",
  "-U",
  "-D",
  "-R",
]);
// git global flags (before the subcommand) that take a value.
const GIT_VALUE_FLAGS = new Set(["-C", "-c"]);

function basename(tok: string): string {
  const slash = tok.lastIndexOf("/");
  return slash >= 0 ? tok.slice(slash + 1) : tok;
}

function tokenize(piece: string): string[] {
  return piece.trim().split(/\s+/).filter(Boolean);
}

const ENV_ASSIGN = /^[A-Za-z_][A-Za-z0-9_]*=/;

/** Strip a leading `sudo` (+ its flags) and `env KEY=val` / bare assignments. */
export function stripPrivilegePrefix(tokens: string[]): string[] {
  let i = 0;
  while (i < tokens.length) {
    const t = tokens[i];
    if (t === "sudo") {
      i++;
      while (i < tokens.length && tokens[i].startsWith("-")) {
        const flag = tokens[i];
        i++;
        if (SUDO_VALUE_FLAGS.has(flag) && i < tokens.length) i++;
      }
      continue;
    }
    if (t === "env") {
      i++;
      while (i < tokens.length && ENV_ASSIGN.test(tokens[i])) i++;
      continue;
    }
    if (ENV_ASSIGN.test(t)) {
      i++;
      continue;
    }
    break;
  }
  return tokens.slice(i);
}

/** First non-flag argument from `start`, skipping value-taking flags. */
function firstArg(
  tokens: string[],
  start: number,
  valueFlags?: Set<string>,
): string | null {
  for (let i = start; i < tokens.length; i++) {
    const t = tokens[i];
    if (t.startsWith("-")) {
      if (valueFlags && valueFlags.has(t)) i++;
      continue;
    }
    return t;
  }
  return null;
}

export interface PackageInstallClass {
  match: boolean;
  ambiguous: boolean;
  manager: string | null;
}

export function classifyPackageInstall(piece: string): PackageInstallClass {
  const toks = stripPrivilegePrefix(tokenize(piece));
  if (toks.length === 0)
    return { match: false, ambiguous: false, manager: null };
  const bin = basename(toks[0]);

  if (DLX_TOOLS.has(bin))
    return { match: true, ambiguous: false, manager: bin };
  if (bin === "pnpm" && toks[1] === "dlx") {
    return { match: true, ambiguous: false, manager: "pnpm dlx" };
  }
  if (
    (bin === "python" || bin === "python3") &&
    toks[1] === "-m" &&
    toks[2] === "pip"
  ) {
    return {
      match: firstArg(toks, 3) === "install",
      ambiguous: false,
      manager: "pip",
    };
  }
  if (bin === "uv" && toks[1] === "pip") {
    return {
      match: firstArg(toks, 2) === "install",
      ambiguous: false,
      manager: "uv pip",
    };
  }

  const spec = PACKAGE_MANAGERS[bin];
  if (spec) {
    const verb = firstArg(toks, 1);
    if (verb === null)
      return { match: spec.bareInstalls, ambiguous: false, manager: bin };
    return { match: spec.verbs.has(verb), ambiguous: false, manager: bin };
  }

  const verb = firstArg(toks, 1);
  if (verb && AMBIGUOUS_INSTALL_VERBS.has(verb)) {
    return { match: false, ambiguous: true, manager: bin };
  }
  return { match: false, ambiguous: false, manager: null };
}

export interface NetworkClass {
  match: boolean;
  tool: string | null;
}

export function classifyNetwork(piece: string): NetworkClass {
  const toks = stripPrivilegePrefix(tokenize(piece));
  if (toks.length === 0) return { match: false, tool: null };
  const bin = basename(toks[0]);

  if (NETWORK_BINS.has(bin)) return { match: true, tool: bin };
  if (DLX_TOOLS.has(bin)) return { match: true, tool: bin };
  if (bin === "pnpm" && toks[1] === "dlx")
    return { match: true, tool: "pnpm dlx" };
  if (bin === "git") {
    const sub = firstArg(toks, 1, GIT_VALUE_FLAGS);
    if (sub && NETWORK_GIT_SUBCMDS.has(sub))
      return { match: true, tool: `git ${sub}` };
  }
  return { match: false, tool: null };
}
