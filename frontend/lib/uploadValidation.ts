export const getUploadFileError = (
  file: File,
  maxSizeMb: number,
  existingNames: string[],
  allowedFileTypes: string[],
): string | null => {
  const extension = file.name.slice(file.name.lastIndexOf('.') + 1).toLowerCase();
  if (!allowedFileTypes.includes(extension)) {
    return `${file.name} is not a supported file type`;
  }

  if (file.size > maxSizeMb * 1024 * 1024) {
    return `${file.name} exceeds ${maxSizeMb}MB limit`;
  }

  if (existingNames.includes(file.name)) {
    return `${file.name} already added`;
  }

  return null;
};
