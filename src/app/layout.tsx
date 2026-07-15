import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { Toaster } from "@/components/ui/toaster";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "MIRAGE — Deception Infrastructure",
  description: "Passive honeytoken dashboard for monitoring data exfiltration attempts. No code execution, no DNS tunneling — just HTTP GET tracking.",
  keywords: ["MIRAGE", "deception", "honeytoken", "canary", "security", "data exfiltration"],
  authors: [{ name: "MIRAGE Project" }],
  icons: {
    icon: "/logo.svg",
  },
  openGraph: {
    title: "MIRAGE — Deception Infrastructure",
    description: "Passive honeytoken dashboard",
    type: "website",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased bg-background text-foreground`}
      >
        {children}
        <Toaster />
      </body>
    </html>
  );
}
