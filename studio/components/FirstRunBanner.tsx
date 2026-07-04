"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";

// Shows a setup prompt across the app until the shared .env is configured.
// Silent when configured or when the API is unreachable (the page's own
// error state handles that case).
export default function FirstRunBanner() {
  const [show, setShow] = useState(false);

  useEffect(() => {
    let live = true;
    api
      .config()
      .then((c) => live && setShow(!c.configured))
      .catch(() => live && setShow(false));
    return () => {
      live = false;
    };
  }, []);

  if (!show) return null;
  return (
    <div className="bg-amber-100 border-b border-amber-200 text-amber-900 text-sm">
      <div className="max-w-7xl mx-auto px-4 py-2 flex items-center gap-2">
        <span>⚙ Not configured yet.</span>
        <Link href="/settings" className="font-medium underline">
          Open Settings
        </Link>
        <span className="text-amber-700">to choose your database and judge, then start analyzing.</span>
      </div>
    </div>
  );
}
