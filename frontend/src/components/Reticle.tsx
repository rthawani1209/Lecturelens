import styles from "./Reticle.module.css";

/** Corner brackets around a frame, like a camera focus box. */
export function Reticle({ children, inset = -4 }: { children: React.ReactNode; inset?: number }) {
  const style = { "--inset": `${inset}px` } as React.CSSProperties;
  return (
    <div className={styles.wrap} style={style}>
      {children}
      <span className={`${styles.c} ${styles.tl}`} aria-hidden="true" />
      <span className={`${styles.c} ${styles.tr}`} aria-hidden="true" />
      <span className={`${styles.c} ${styles.bl}`} aria-hidden="true" />
      <span className={`${styles.c} ${styles.br}`} aria-hidden="true" />
    </div>
  );
}
