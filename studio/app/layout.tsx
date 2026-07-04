import "./globals.css";
import type { Metadata } from "next";
import Link from "next/link";
import FirstRunBanner from "@/components/FirstRunBanner";

export const metadata: Metadata = {
  title: "Session Analytics Studio",
  description: "Copilot session analytics & process mining (CCT #63)",
};

const TABS = [
  { href: "/", label: "Dashboard" },
  { href: "/sessions", label: "Sessions" },
  { href: "/graph", label: "Knowledge Graph" },
  { href: "/analysis", label: "Analysis" },
  { href: "/agents", label: "Agents" },
  { href: "/settings", label: "Settings" },
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="min-h-screen flex flex-col">
          <header className="bg-slate-900 text-white">
            <div className="max-w-7xl mx-auto px-4 flex items-center gap-6 h-14">
              <span className="font-semibold tracking-tight">⬡ Session Analytics</span>
              <nav className="flex gap-1 text-sm">
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
          <main className="flex-1 max-w-7xl w-full mx-auto px-4 py-6">{children}</main>
        </div>
      </body>
    </html>
  );
}
