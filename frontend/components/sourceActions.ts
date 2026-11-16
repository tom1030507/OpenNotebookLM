import { ApiError, type Document } from '@/lib/api';

export type AddSourcesOpenChange = (isOpen: boolean) => void;

/** Files from one batch that could not be added, with the reason for each. */
export interface FileUploadOutcome {
  failed: { file: File; message: string }[];
}

// An account may run two imports at once and ten a minute; the server answers
// anything past that with 429 and says when to come back. Waiting that long is
// how a batch larger than two goes through, so a refusal is only final once a
// file has waited this long in total.
const MAX_WAIT_PER_FILE_MS = 3 * 60 * 1000;
const MAX_SINGLE_WAIT_MS = 60 * 1000;

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));


export function requestAddSources(
  hasCurrentProject: boolean,
  onAddSourcesOpenChange: AddSourcesOpenChange,
): void {
  if (hasCurrentProject) {
    onAddSourcesOpenChange(true);
  }
}


export async function closeAddSourcesAfterSuccessfulUpload(
  uploadSources: () => Promise<void>,
  onAddSourcesOpenChange: AddSourcesOpenChange,
): Promise<void> {
  await uploadSources();
  onAddSourcesOpenChange(false);
}


/**
 * Files the project already holds, judged by the name and size recorded at
 * upload. A content hash would be exact, but the server has none for the
 * file itself; name and size together are what a person would compare.
 *
 * @param files Files about to be uploaded.
 * @param documents The project's current sources.
 * @returns The files that match an existing source.
 */
export const findDuplicateFiles = (files: File[], documents: Document[]): File[] => (
  files.filter((file) => documents.some((document) => (
    document.meta?.filename === file.name && document.meta?.file_size === file.size
  )))
);


/**
 * Upload files one at a time, waiting out the server's rate refusals.
 *
 * A file that still fails is reported rather than ending the batch, so the
 * files after it are attempted and the caller can keep only the failures.
 *
 * @param files Files in the order the reader chose them.
 * @param upload Uploads one file.
 * @param wait Pause between attempts; injectable for tests.
 * @returns The files that were not added, each with its reason.
 */
export async function uploadFilesInTurn(
  files: File[],
  upload: (file: File) => Promise<unknown>,
  wait: (ms: number) => Promise<void> = sleep,
): Promise<FileUploadOutcome> {
  const failed: FileUploadOutcome['failed'] = [];

  for (const file of files) {
    let waited = 0;
    let attempt = 0;
    for (;;) {
      try {
        await upload(file);
        break;
      } catch (error) {
        const refusedForRate = error instanceof ApiError && error.status === 429;
        // Backing off as well as honouring Retry-After: each retry sends the
        // whole file again, and a large one can keep its slot for minutes.
        const delay = Math.min(
          MAX_SINGLE_WAIT_MS,
          Math.max((error as ApiError).retryAfterSeconds ?? 1, 2 ** attempt) * 1000,
        );
        if (!refusedForRate || waited + delay > MAX_WAIT_PER_FILE_MS) {
          failed.push({
            file,
            message: error instanceof Error ? error.message : 'Upload failed',
          });
          break;
        }
        await wait(delay);
        waited += delay;
        attempt += 1;
      }
    }
  }

  return { failed };
}
