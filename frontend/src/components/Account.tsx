"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { api, type Me } from "@/lib/api";
import styles from "./TopBar.module.css";

function initials(me: Me): string {
  const from = me.name || me.email.split("@")[0];
  return from
    .split(/[\s._-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]!.toUpperCase())
    .join("");
}

export function Account() {
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  const [open, setOpen] = useState(false);
  const menu = useRef<HTMLDivElement>(null);
  const path = usePathname();
  const router = useRouter();

  useEffect(() => {
    api
      .me()
      .then(setMe)
      .catch(() => setMe(null));
  }, [path]);

  useEffect(() => {
    if (!open) return;
    function close(e: MouseEvent | KeyboardEvent) {
      if (
        e instanceof KeyboardEvent ? e.key === "Escape" : !menu.current?.contains(e.target as Node)
      )
        setOpen(false);
    }
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open]);

  if (me === undefined) return <span className={styles.avatarSlot} aria-hidden="true" />;

  if (me === null) {
    return (
      <Link href={`/signin?next=${encodeURIComponent(path)}`} className={styles.signIn}>
        Sign in
      </Link>
    );
  }

  return (
    <div className={styles.account} ref={menu}>
      <button
        type="button"
        className={styles.avatar}
        aria-label={`Account: ${me.email}`}
        aria-expanded={open}
        aria-haspopup="menu"
        onClick={() => setOpen((o) => !o)}
      >
        {initials(me)}
      </button>
      {open && (
        <div className={styles.menu} role="menu">
          <p className={`mono ${styles.menuEmail}`}>{me.email}</p>
          <button
            type="button"
            role="menuitem"
            onClick={async () => {
              await api.logout().catch(() => undefined);
              setMe(null);
              setOpen(false);
              router.refresh();
            }}
          >
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}
