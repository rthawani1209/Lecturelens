import type { Metadata } from "next";
import localFont from "next/font/local";
import { TopBar } from "@/components/TopBar";
import "./globals.css";

// self-hosted: fetching from Google Fonts at build time kept failing CI and deploys.
// (next/font needs these written out as literals)
const display = localFont({
  src: [
    { path: "../fonts/unbounded-latin-400-normal.woff2", weight: "400" },
    { path: "../fonts/unbounded-latin-500-normal.woff2", weight: "500" },
  ],
  variable: "--font-display",
});
const sans = localFont({
  src: [
    { path: "../fonts/instrument-sans-latin-400-normal.woff2", weight: "400" },
    { path: "../fonts/instrument-sans-latin-500-normal.woff2", weight: "500" },
    { path: "../fonts/instrument-sans-latin-600-normal.woff2", weight: "600" },
    { path: "../fonts/instrument-sans-latin-700-normal.woff2", weight: "700" },
  ],
  variable: "--font-sans",
});
const mono = localFont({
  src: [
    { path: "../fonts/jetbrains-mono-latin-400-normal.woff2", weight: "400" },
    { path: "../fonts/jetbrains-mono-latin-500-normal.woff2", weight: "500" },
  ],
  variable: "--font-mono",
});

export const metadata: Metadata = {
  title: "LectureLens",
  description:
    "Search inside lecture videos: what was said, written on the board, or shown on a slide.",
};

// set the saved theme before paint so light mode doesn't flash dark
const themeScript = `try{var t=localStorage.getItem("ll-theme");if(t)document.documentElement.dataset.theme=t}catch(e){}`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={`${display.variable} ${sans.variable} ${mono.variable}`}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body>
        <TopBar />
        {children}
      </body>
    </html>
  );
}
