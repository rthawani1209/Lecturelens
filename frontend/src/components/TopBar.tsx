"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Account } from "./Account";
import { Logo } from "./Logo";
import { ThemeToggle } from "./ThemeToggle";
import styles from "./TopBar.module.css";

const NAV = [
  { href: "/search", label: "Search" },
  { href: "/watch", label: "Watch" },
  { href: "/study", label: "Study" },
  { href: "/upload", label: "Upload" },
];

export function TopBar() {
  const path = usePathname();
  return (
    <header className={styles.bar}>
      <Logo />
      <nav aria-label="Main" className={styles.nav}>
        {NAV.map((n) => {
          const on = path.startsWith(n.href);
          return (
            <Link
              key={n.href}
              href={n.href}
              className={on ? `${styles.link} ${styles.on}` : styles.link}
              aria-current={on ? "page" : undefined}
            >
              {n.label}
            </Link>
          );
        })}
      </nav>
      <div className={styles.tools}>
        <ThemeToggle />
        <Account />
      </div>
    </header>
  );
}
