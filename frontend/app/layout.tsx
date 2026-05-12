import type { Metadata } from "next";
import "streamdown/styles.css";
import "./globals.css";

export const metadata: Metadata = {
  title: "QueryPilot",
  description: "A Text-to-SQL chatbot for Supabase data."
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
