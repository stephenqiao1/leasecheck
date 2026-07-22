"use client";

import Link from "next/link";
import styles from "./document.module.css";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className={styles.status}>
      <p className={styles.statusTitle}>Couldn&apos;t load this document</p>
      <p>{error.message || "The document may not exist, or the API is unreachable."}</p>
      <div>
        <button type="button" className={styles.retryBtn} onClick={() => reset()}>
          Try again
        </button>
      </div>
      <Link href="/" className={styles.backLink}>
        Enter a different document ID
      </Link>
    </div>
  );
}
