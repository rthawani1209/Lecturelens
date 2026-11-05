import Link from "next/link";
import styles from "@/components/Watch.module.css";

export default function NotFound() {
  return (
    <main className={styles.page}>
      <div className={styles.missing}>
        <p className="label">404</p>
        <h1 className="display">There&apos;s no page here.</h1>
        <Link href="/">Back to search</Link>
      </div>
    </main>
  );
}
