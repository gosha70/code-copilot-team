/**
 * Sandbox detection + the autonomous/ci "no unrestricted host" gate (T10.1,
 * FR-019).
 *
 * Classifies the execution environment into one of the FR-019 states and
 * enforces the rule that the `autonomous`/`ci` postures reject unrestricted host
 * execution absent an explicit override. Detection is best-effort from host
 * signals via pluggable SandboxProviders (Docker ships first).
 *
 * SEPARATION OF CONCERNS (spec P5): permissions are NOT sandboxing. A
 * permission-gated session on a bare host is `host-unrestricted` here — the
 * permission engine limits what the agent is ASKED to do, the sandbox limits
 * what the process CAN do. They are reported independently and never conflated.
 */

import * as fs from "node:fs";

export type SandboxState =
  | "host-unrestricted"
  | "permission-gated-only"
  | "containerized"
  | "micro-vm"
  | "remote-sandboxed"
  | "external-policy-controlled";

export interface SandboxDetection {
  state: SandboxState;
  provider: string; // which SandboxProvider matched ("docker", "env", "none")
  evidence: string[]; // observable signals that produced the classification
}

/** A pluggable detector. Returns a detection when it matches, else null. */
export interface SandboxProvider {
  id: string;
  detect(env: Record<string, string | undefined>): SandboxDetection | null;
}

function fileExists(p: string): boolean {
  try {
    return fs.existsSync(p);
  } catch {
    return false;
  }
}

function readSafe(p: string): string {
  try {
    return fs.readFileSync(p, "utf8");
  } catch {
    return "";
  }
}

/** Docker/OCI-container backend: cgroup + /.dockerenv + env markers. */
export const dockerProvider: SandboxProvider = {
  id: "docker",
  detect(env) {
    const evidence: string[] = [];
    if (fileExists("/.dockerenv")) evidence.push("/.dockerenv present");
    const cgroup = readSafe("/proc/1/cgroup") + readSafe("/proc/self/cgroup");
    if (/docker|containerd|kubepods|libpod/.test(cgroup)) {
      evidence.push("container cgroup match");
    }
    if (env.container === "docker" || env.container === "podman") {
      evidence.push(`env container=${env.container}`);
    }
    if (evidence.length > 0) {
      return { state: "containerized", provider: "docker", evidence };
    }
    return null;
  },
};

/**
 * Explicit-declaration backend: an operator/harness that runs under a micro-VM
 * or a remote sandbox declares it via CCT_SANDBOX (the runtime cannot detect
 * those from inside). CCT_SANDBOX=containerized is also honored for harnesses
 * that isolate without the Docker signals above.
 */
export const envProvider: SandboxProvider = {
  id: "env",
  detect(env) {
    const declared = env.CCT_SANDBOX;
    const map: Record<string, SandboxState> = {
      "micro-vm": "micro-vm",
      microvm: "micro-vm",
      remote: "remote-sandboxed",
      "remote-sandboxed": "remote-sandboxed",
      containerized: "containerized",
      "external-policy-controlled": "external-policy-controlled",
      "external-policy": "external-policy-controlled",
      // permission-gated-only is declarable/reportable but is NOT a sandbox
      // (permissions != sandboxing, P5) — the gate below does not accept it.
      "permission-gated-only": "permission-gated-only",
      "permission-gated": "permission-gated-only",
      // Explicit bare-host declaration (an operator on an unrestricted host, or
      // a deterministic test) — forces host-unrestricted over FS sniffing.
      host: "host-unrestricted",
      none: "host-unrestricted",
      "host-unrestricted": "host-unrestricted",
    };
    if (declared && map[declared]) {
      return {
        state: map[declared],
        provider: "env",
        evidence: [`CCT_SANDBOX=${declared}`],
      };
    }
    return null;
  },
};

// Explicit declaration wins over host sniffing.
const PROVIDERS: SandboxProvider[] = [envProvider, dockerProvider];

export function detectSandbox(
  env: Record<string, string | undefined> = process.env,
): SandboxDetection {
  for (const provider of PROVIDERS) {
    const detection = provider.detect(env);
    if (detection) return detection;
  }
  return { state: "host-unrestricted", provider: "none", evidence: [] };
}

export interface SandboxGateResult {
  allowed: boolean;
  state: SandboxState;
  required: boolean;
  overridden: boolean;
  reason: string;
}

/**
 * The autonomous/ci rejection rule. When the config requires a sandbox
 * (`security.sandbox_required` or `autonomy.reject_unrestricted_host`) AND the
 * detected state provides no OS sandbox (`host-unrestricted` or `permission-gated-only`), execution is REJECTED — fail-closed —
 * unless an explicit override is set (which is allowed but recorded). Any
 * containerized / micro-vm / remote-sandboxed / external-policy-controlled
 * satisfies the requirement; permission-gated-only does NOT (permissions != sandbox).
 */
export function sandboxGate(
  detection: SandboxDetection,
  opts: {
    sandboxRequired: boolean;
    rejectUnrestrictedHost: boolean;
    override: boolean;
  },
): SandboxGateResult {
  const required = opts.sandboxRequired || opts.rejectUnrestrictedHost;
  // "No OS sandbox" — the process is unrestricted at the OS level, so a required
  // sandbox is NOT satisfied. permission-gated-only counts here: permissions are
  // not sandboxing (P5). Only containerized / micro-vm / remote-sandboxed /
  // external-policy-controlled genuinely restrict what the process CAN do.
  const noOsSandbox =
    detection.state === "host-unrestricted" ||
    detection.state === "permission-gated-only";

  if (required && noOsSandbox) {
    if (opts.override) {
      return {
        allowed: true,
        state: detection.state,
        required,
        overridden: true,
        reason:
          `sandbox required but no OS sandbox is present (${detection.state}) — permitted via explicit override (CCT_SANDBOX_OVERRIDE=1), recorded`,
      };
    }
    return {
      allowed: false,
      state: detection.state,
      required,
      overridden: false,
      reason:
        `sandbox required (autonomous/ci posture) but the environment provides no OS sandbox (${detection.state}) — refusing; run in a container/micro-VM/remote sandbox or set CCT_SANDBOX_OVERRIDE=1 (audited)`,
    };
  }

  return {
    allowed: true,
    state: detection.state,
    required,
    overridden: false,
    reason: required
      ? `sandbox requirement satisfied by ${detection.state}`
      : `no sandbox required (${detection.state})`,
  };
}
