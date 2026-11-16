'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { clearSession, isOfflineDemoSession } from '@/lib/session';
import useStore from '@/store/useStore';

/** Label bundled data so preview content cannot be mistaken for saved research. */
export default function OfflineDemoNotice() {
  const [active, setActive] = useState(false);
  const router = useRouter();

  useEffect(() => setActive(isOfflineDemoSession()), []);

  if (!active) return null;

  return (
    <section aria-label="Offline demo" role="status" className="flex shrink-0 items-center justify-between gap-4 border-b border-[var(--border)] bg-[var(--muted)] px-4 py-2 text-xs sm:px-6 sm:text-sm">
      <p>
        <span className="font-medium">Offline demo</span>
        <span className="text-[var(--muted-foreground)]"> · Sample data. Uploads, changes and generation need a running backend</span>
      </p>
      <button
        type="button"
        className="h-8 shrink-0 rounded-md border border-[var(--input)] bg-[var(--card)] px-3 text-xs hover:bg-[var(--secondary)] transition-base"
        onClick={() => {
          useStore.getState().clearAccountState();
          clearSession();
          router.replace('/login');
        }}
      >
        Exit demo
      </button>
    </section>
  );
}
