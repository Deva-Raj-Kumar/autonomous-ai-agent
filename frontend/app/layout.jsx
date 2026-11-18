// Root layout: wraps EVERY page. A server component; AuthProvider inside is a client one.
import "./globals.css";

import { AuthProvider } from "@/lib/auth";

export const metadata = {
  title: "Vision AI",
  description: "Your Personal AI Assistant with Memory Bank and Knowledge RAG.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
