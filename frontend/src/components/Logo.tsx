import Link from "next/link";
import styles from "./TopBar.module.css";

export function Logo() {
  return (
    <Link href="/" className={styles.logo}>
      <svg width="30" height="30" viewBox="0 0 30 30" aria-hidden="true">
        <circle cx="15" cy="15" r="11" fill="none" stroke="currentColor" strokeWidth="1.5" />
        <circle cx="15" cy="15" r="4" fill="var(--accent)" />
        <path d="M15 1v5M15 24v5M1 15h5M24 15h5" stroke="currentColor" strokeWidth="1.5" />
      </svg>
      <span className="display">LectureLens</span>
    </Link>
  );
}
