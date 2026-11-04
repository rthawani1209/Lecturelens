import type { Metadata } from "next";
import { Instrument_Sans, JetBrains_Mono, Unbounded } from "next/font/google";
import { TopBar } from "@/components/TopBar";
import "./globals.css";

const display = Unbounded({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-display",
});
const sans = Instrument_Sans({ subsets: ["latin"], variable: "--font-sans" });
const mono = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
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
