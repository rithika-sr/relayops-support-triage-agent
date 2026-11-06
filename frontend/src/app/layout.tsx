import type { Metadata, Viewport } from "next";
import { Providers } from "@/components/providers";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "RelayOps", template: "%s · RelayOps" },
  description: "Support-to-engineering triage with bounded, reviewed investigations.",
};

export const viewport: Viewport = { themeColor: "#111d2f", width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-paper text-text">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
