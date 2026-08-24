import { useEffect, useRef } from 'react';
import toast from 'react-hot-toast';

import useStore from '@/store/useStore';
import type { DocumentStatus } from '@/lib/api';

export const POLL_INTERVAL_MS = 2000;
// Indexing a long page takes tens of seconds, but a document that never
// settles should not keep a forgotten tab polling for the rest of the day.
export const MAX_POLLS = 150;

const isPending = (status: string) => status === 'queued' || status === 'processing';

/**
 * Keep watching a source until it is usable.
 *
 * A document only reports `ready` once the backend can retrieve it, which
 * happens well after the upload request returns. Nothing else re-checks, so
 * without this the list sits at "Processing..." and the composer stays
 * disabled until the reader reloads the page.
 */
export default function useDocumentStatusWatch() {
  const projectId = useStore((state) => state.currentProject?.id);
  const refreshDocuments = useStore((state) => state.refreshDocuments);
  const documents = useStore((state) => state.documents);
  const notifyOnProcessingComplete = useStore((state) => state.notifyOnProcessingComplete);
  const watchedStatuses = useRef(new Map<string, DocumentStatus>());
  const pollGeneration = useRef(0);
  // A plain string so the effect only restarts when the pending set changes.
  const pendingIds = useStore((state) => state.documents
    .filter((document) => isPending(document.status))
    .map((document) => document.id)
    .join(','));

  useEffect(() => {
    if (!projectId || !pendingIds) return;

    const generation = pollGeneration.current + 1;
    pollGeneration.current = generation;
    let cancelled = false;
    let polls = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | undefined;

    const schedule = () => {
      timer = setTimeout(() => {
        void poll();
      }, POLL_INTERVAL_MS);
    };

    const poll = async () => {
      if (cancelled || pollGeneration.current !== generation) return;

      polls += 1;
      if (polls > MAX_POLLS) {
        return;
      }

      controller = new AbortController();
      try {
        await refreshDocuments(
          projectId,
          controller.signal,
          () => !cancelled && pollGeneration.current === generation,
        );
      } finally {
        if (!cancelled && pollGeneration.current === generation && polls < MAX_POLLS) {
          schedule();
        }
      }
    };

    schedule();

    return () => {
      cancelled = true;
      controller?.abort();
      if (timer) clearTimeout(timer);
    };
  }, [projectId, pendingIds, refreshDocuments]);

  // Polling is what notices that a source has settled, so this is where the
  // "notify when processing is finished" preference is honoured.
  useEffect(() => {
    const previousStatuses = watchedStatuses.current;
    const currentStatuses = new Map<string, DocumentStatus>();

    documents.forEach((document) => {
      currentStatuses.set(document.id, document.status);

      const previousStatus = previousStatuses.get(document.id);
      const hasJustSettled = previousStatus
        && isPending(previousStatus)
        && !isPending(document.status);
      if (!hasJustSettled || !notifyOnProcessingComplete) return;

      if (document.status === 'ready') {
        toast.success(`${document.name} is ready`);
      } else {
        toast.error(`${document.name} could not be processed`);
      }
    });

    watchedStatuses.current = currentStatuses;
  }, [documents, notifyOnProcessingComplete]);
}
