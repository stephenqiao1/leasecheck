import styles from "./document.module.css";

export default function Loading() {
  return (
    <div className={styles.status}>
      <p className={styles.statusTitle}>Loading document…</p>
      <p>Fetching clauses and findings.</p>
    </div>
  );
}
