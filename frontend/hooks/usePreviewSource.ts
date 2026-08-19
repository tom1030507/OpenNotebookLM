'use client';

import { useEffect, useState } from 'react';

import api, { needsAuthorizedFetch, type Document } from '@/lib/api';

export interface PreviewSource {
  /** Address to hand a viewer element, or null while there is not one yet. */
  src: string | null;
  /** Why the file could not be loaded, when it could not be. */
  error: string | null;
}

/**
 * Resolve an address a preview pane can actually load for a document.
 *
 * An external source is already loadable and is returned as it stands. An
 * uploaded file is served by the API's protected file route, and a browser
 * cannot put an Authorization header on an `<iframe src>`, so those bytes are
 * fetched through the API client — which does send the token — and handed back
 * as an object URL. The URL is released when the preview goes away.
 *
 * Args:
 *   document: The document being previewed
 *
 * Returns:
 *   The address to load and the reason there is not one, if there is not
 */
export default function usePreviewSource(document: Document): PreviewSource {
  const authorized = Boolean(document.url) && needsAuthorizedFetch(document);
  const [fetched, setFetched] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!authorized) {
      return undefined;
    }

    let objectUrl: string | null = null;
    let abandoned = false;

    setError(null);
    api.fetchDocumentFile(document.id)
      .then((file) => {
        if (abandoned) {
          return;
        }

        objectUrl = URL.createObjectURL(file);
        setFetched(objectUrl);
      })
      .catch((cause: unknown) => {
        if (abandoned) {
          return;
        }

        setError(
          cause instanceof Error ? cause.message : 'Could not load the file',
        );
      });

    return () => {
      abandoned = true;

      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [authorized, document.id]);

  return {
    src: authorized ? fetched : document.url ?? null,
    error,
  };
}
