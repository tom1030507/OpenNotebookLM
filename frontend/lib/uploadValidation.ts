export const getUploadFileError = (
  file: File,
  maxSizeMb: number,
  existingNames: string[],
): string | null => {
  if (!file.name.toLowerCase().endsWith('.pdf')) {
    return `${file.name} is not a supported PDF file`;
  }

  if (file.size > maxSizeMb * 1024 * 1024) {
    return `${file.name} exceeds ${maxSizeMb}MB limit`;
  }

  if (existingNames.includes(file.name)) {
    return `${file.name} already added`;
  }

  return null;
};
