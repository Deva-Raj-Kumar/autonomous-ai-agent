"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { useAuth } from "@/lib/auth";

const LINKS = [
  { href: "/", label: "Dashboard" },
  { href: "/chat", label: "Chat" },
  { href: "/memories", label: "Memories" },
  { href: "/knowledge", label: "Knowledge" },
];

export default function NavBar() {
  const pathname = usePathname();
  const { user, logout } = useAuth();
  return (
    <header className="nav">
      <Link href="/" className="brand">Autonomous Agent</Link>
      <nav aria-label="Main">
        {LINKS.map((link) => {
          const active = link.href === "/" ? pathname === "/" || pathname.startsWith("/runs") : pathname.startsWith(link.href);
          return (
            <Link key={link.href} href={link.href} className={active ? "active" : undefined} aria-current={active ? "page" : undefined}>
              {link.label}
            </Link>
          );
        })}
      </nav>
      <div className="nav-user">
        <span className="small">{user?.username}{user?.is_admin ? " (admin)" : ""}</span>
        <button type="button" className="link-button" onClick={logout}>Log out</button>
      </div>
    </header>
  );
}
