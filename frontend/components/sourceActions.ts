export type AddSourcesOpenChange = (isOpen: boolean) => void;


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
