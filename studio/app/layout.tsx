import "./globals.css";
import type { Metadata } from "next";
import Link from "next/link";
import FirstRunBanner from "@/components/FirstRunBanner";

export const metadata: Metadata = {
  title: "Session Analytics Studio",
  description: "Copilot session analytics & process mining (CCT #63)",
};

// #307: only pages that answer a question a person has. Clusters is
// gone (falsified on real data — one giant component); Graph explores
// a session or a project and what it is connected to. Search is gone —
// it read only archived text, which most stores have none of; Ask
// answers questions in words through read-only lookups, text search
// among them. Routing is a card on Benchmark (both are
// benchmark-derived, /routing stays); the client-side Agents stub is
// gone — Learn (#309) carries the real catalogue of docs, skills and
// agents from the repo itself.
const TABS = [
  { href: "/", label: "Dashboard" },
  { href: "/sessions", label: "Sessions" },
  { href: "/ask", label: "Ask" },
  { href: "/graph", label: "Graph" },
  { href: "/analysis", label: "Analysis" },
  { href: "/benchmark", label: "Benchmark" },
  { href: "/learn", label: "Learn" },
  { href: "/settings", label: "Settings" },
];

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <div className="min-h-screen flex flex-col">
          <header className="bg-slate-900 text-white">
            <div className="max-w-7xl mx-auto px-4 flex items-center gap-6 h-14">
              {/* The logo links home — a wordmark in a nav bar that is not
                  clickable is a dead spot users try anyway. */}
              <Link
                href="/"
                className="flex items-center gap-2 font-semibold tracking-tight whitespace-nowrap shrink-0 hover:opacity-90"
              >
                {/* Plain <img>, not next/image: a fixed-size local asset
                    gains nothing from the optimizer. Sized in CSS AND in
                    the attributes so the header cannot jump while it
                    loads. object-contain because the artwork is not
                    perfectly square (253x256) — forcing it into a square
                    box would squash it; no rounding, because the logo is
                    transparent and has no box to round. */}
                <img
                  src="/logo.png"
                  alt=""
                  width={28}
                  height={28}
                  className="w-7 h-7 object-contain"
                />
                Session Analytics
              </Link>
              <nav className="flex gap-1 text-sm overflow-x-auto whitespace-nowrap">
                {TABS.map((t) => (
                  <Link
                    key={t.href}
                    href={t.href}
                    className="px-3 py-1.5 rounded hover:bg-slate-700 transition-colors"
                  >
                    {t.label}
                  </Link>
                ))}
              </nav>
            </div>
          </header>
          <FirstRunBanner />
          <main className="flex-1 max-w-7xl w-full mx-auto px-4 py-6">
            {children}
          </main>
        </div>
      </body>
    </html>
  );
}
