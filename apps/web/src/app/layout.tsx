import type { Metadata, Viewport } from "next";
import { SPRITE_SVG } from "@/components/sprite";
import "../design/fonts.css";
import "../design/tokens.css";
import "../design/base.css";
import "../design/components.css";
import "../design/directions.css";
import "../design/survey.css";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "Nigiwai", template: "%s · Nigiwai" },
  description: "Nigiwai reads the crowd your venue already has, from what your guests say they love.",
  icons: {
    icon: "/icon.svg",
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f3eada" },
    { media: "(prefers-color-scheme: dark)", color: "#1b2030" },
  ],
};

// Runs before first paint so the page never flashes the wrong theme. Direction A is the shipped direction.
const THEME_BOOT = `(function(){try{var t=localStorage.getItem('nigiwai-theme');if(t!=='light'&&t!=='dark'){t=matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'}document.documentElement.setAttribute('data-theme',t)}catch(e){document.documentElement.setAttribute('data-theme','light')}})();`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" data-dir="a" data-theme="light" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOT }} />
      </head>
      <body>
        <div dangerouslySetInnerHTML={{ __html: SPRITE_SVG }} />
        {children}
      </body>
    </html>
  );
}
