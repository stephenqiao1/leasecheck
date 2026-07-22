"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

export default function Home() {
  const [id, setId] = useState("");
  const router = useRouter();

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = id.trim();
    if (trimmed) {
      router.push(`/documents/${encodeURIComponent(trimmed)}`);
    }
  }

  return (
    <main className="flex min-h-screen flex-col items-center justify-center px-6">
      <div className="w-full max-w-md">
        <h1
          className="text-4xl text-ink"
          style={{ fontFamily: "var(--font-serif), serif" }}
        >
          LeaseCheck
        </h1>
        <p
          className="mt-2 text-sm text-[color:var(--ink-soft)]"
          style={{ fontFamily: "var(--font-sans), sans-serif" }}
        >
          Open a reviewed lease by its document ID.
        </p>

        <form onSubmit={handleSubmit} className="mt-8">
          <label
            htmlFor="doc-id"
            className="block text-xs uppercase tracking-wider text-[color:var(--ink-faint)]"
            style={{ fontFamily: "var(--font-sans), sans-serif" }}
          >
            Document ID
          </label>
          <input
            id="doc-id"
            value={id}
            onChange={(e) => setId(e.target.value)}
            placeholder="00000000-0000-0000-0000-000000000000"
            autoComplete="off"
            spellCheck={false}
            className="mt-2 w-full border border-[color:var(--rule-line)] bg-transparent px-3 py-2 text-sm text-ink outline-none focus:border-[color:var(--ink-faint)]"
            style={{ fontFamily: "var(--font-mono), monospace" }}
          />
          <button
            type="submit"
            disabled={!id.trim()}
            className="mt-4 w-full border border-[color:var(--ink)] bg-[color:var(--ink)] px-3 py-2 text-xs uppercase tracking-wider text-[color:var(--paper)] transition-opacity disabled:opacity-40"
            style={{ fontFamily: "var(--font-sans), sans-serif" }}
          >
            Open document
          </button>
        </form>
      </div>
    </main>
  );
}
