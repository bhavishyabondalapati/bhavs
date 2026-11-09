import type { Metadata, Viewport } from "next";
import Header from "@/components/Header";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "bhavs", template: "%s · bhavs" },
  description: "bhavs: an independent streaming platform for open-licensed films. A portfolio project.",
};
export const viewport: Viewport = { themeColor: "#0d1117" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <a href="#main" className="skip-link">Skip to content</a>
        <Header />
        <main id="main" tabIndex={-1}>{children}</main>
      </body>
    </html>
  );
}
