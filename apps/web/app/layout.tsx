import type { Metadata } from "next";
import { Sidebar } from "@/components/sidebar";
import { Topbar } from "@/components/topbar";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "PDI", template: "%s · PDI" },
  description: "Private, self-hosted document intelligence.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <div className="flex min-h-dvh">
          <Sidebar />
          <div className="min-w-0 flex-1">
            <Topbar />
            <main>{children}</main>
          </div>
        </div>
      </body>
    </html>
  );
}
