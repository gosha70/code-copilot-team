/**
 * Project-trust gating helpers (spec FR-004a, V1/V2; authored).
 *
 * CCT observes Pi's `project_trust` lifecycle but never owns the decision
 * (V1): the first extension to answer owns it, and CCT deliberately returns
 * no decision. What CCT must do is react honestly to the decision it sees.
 *
 * Two obligations live here because both need to be testable without a live
 * Pi session:
 *
 *   1. Trust resolved mid-session cannot retroactively load project
 *      configuration. The layered config was already resolved with the trust
 *      value in effect at session start, and re-resolving it underneath a
 *      running session would change permissions and gates after decisions had
 *      already been made against the old values. So a change is reported and
 *      a restart is required — the session is never silently re-trusted.
 *
 *   2. `defaultProjectTrust: "always"` means Pi grants trust with no saved
 *      user decision, so project config can load in a headless session that
 *      no human approved. That is legitimate configuration, not a fault, but
 *      it must leave an audit trail rather than only a console warning.
 */

export type TrustState = "trusted" | "untrusted" | "unknown";

/** Pi's setting value that grants trust without a recorded user decision. */
export const DEFAULT_PROJECT_TRUST_ALWAYS = "always";

export interface TrustDrift {
  from: TrustState;
  to: TrustState;
  message: string;
}

/**
 * Compare the trust the configuration was loaded with against the trust now
 * in effect. Returns null while they agree.
 */
export function trustDrift(
  loadedWith: TrustState,
  current: TrustState,
): TrustDrift | null {
  if (loadedWith === current) return null;
  const gained = current === "trusted";
  return {
    from: loadedWith,
    to: current,
    message:
      `Project trust changed this session (${loadedWith} -> ${current}). ` +
      (gained
        ? "Project CCT configuration was NOT loaded for this session and will not be applied retroactively. "
        : "Project CCT configuration loaded earlier in this session remains in effect. ") +
      "Restart pi-code for the new trust decision to take effect.",
  };
}

export interface DefaultTrustFinding {
  warning: string;
  /** Audit payload; `origin` is fixed so the record is greppable. */
  audit: { origin: "trust"; decision: string; rule: string; subject: string };
}

/**
 * Build the warning and audit record for Pi's `defaultProjectTrust` setting.
 * Returns null for any value other than "always" — nothing to report.
 */
export function defaultProjectTrustFinding(
  value: string | null,
): DefaultTrustFinding | null {
  if (value !== DEFAULT_PROJECT_TRUST_ALWAYS) return null;
  return {
    warning:
      `Pi defaultProjectTrust is '${DEFAULT_PROJECT_TRUST_ALWAYS}': non-interactive sessions trust ` +
      "projects without a saved decision. Project CCT configuration may load headlessly " +
      "(audit origin: defaultProjectTrust).",
    audit: {
      origin: "trust",
      decision: "trusted-without-saved-decision",
      rule: "pi.defaultProjectTrust",
      subject: `defaultProjectTrust=${DEFAULT_PROJECT_TRUST_ALWAYS}`,
    },
  };
}
