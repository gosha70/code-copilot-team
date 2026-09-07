"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, ConfigResponse } from "@/lib/api";

// Shown ONLY when the tool genuinely cannot be used, and then it names
// the specific thing that is missing and the exact step that fixes it.
//
// The previous version said "Not configured yet — open Settings to
// choose your database and judge" on every page, keyed off whether a
// .env file existed. That was wrong in both directions: it fired on a
// perfectly working install started with `--db` (the same page showed a
// healthy store and 132 sessions underneath it), and it never said what
// "configured" would mean or how you would know you were done. A
// warning that cannot be satisfied and cannot be verified is noise, and
// users learn to ignore the banner area entirely.
//
// Now: readiness is a capability (store reachable AND holding sessions),
// each failing case gets its own message, and a judge is never mentioned
// because analytics do not need one.
export default function FirstRunBanner() {
  const [cfg, setCfg] = useState<ConfigResponse | null>(null);

  useEffect(() => {
    let live = true;
    api
      .config()
      .then((c) => live && setCfg(c))
      // An unreachable API is the page's own error state, not ours.
      .catch(() => live && setCfg(null));
    return () => {
      live = false;
    };
  }, []);

  if (!cfg || cfg.configured) return null;

  const r = cfg.readiness;
  // Two genuinely different problems, two different fixes. Collapsing
  // them into one message is what made the old banner unactionable.
  const noStore = !r || !r.store_reachable;
  const emptyStore = !noStore && r.sessions === 0;
  if (!noStore && !emptyStore) return null;

  return (
    <div className="bg-amber-100 border-b border-amber-200 text-amber-900 text-sm">
      <div className="max-w-7xl mx-auto px-4 py-2">
        {noStore ? (
          <>
            <span className="font-medium">No database yet.</span>{" "}
            <span>
              Analytics need somewhere to store your sessions. Set one in{" "}
              <Link href="/settings" className="font-medium underline">
                Settings → Database
              </Link>{" "}
              (a local SQLite file is fine), then run{" "}
              <code className="bg-amber-50 px-1 rounded font-mono text-xs">
                session-analytics start
              </code>
              . This banner disappears once the store holds sessions.
            </span>
          </>
        ) : (
          <>
            <span className="font-medium">
              Database connected, but no sessions ingested yet.
            </span>{" "}
            <span>
              Run{" "}
              <code className="bg-amber-50 px-1 rounded font-mono text-xs">
                session-analytics ingest
              </code>{" "}
              to read your copilot transcripts into it. This banner disappears
              as soon as the first session lands.
            </span>
          </>
        )}
      </div>
    </div>
  );
}
