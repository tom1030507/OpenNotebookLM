export const SUPPORTED_UPLOAD_FILE_EXTENSIONS = [
  '.pdf',
  '.txt',
  '.md',
  '.docx',
  '.pptx',
  '.xlsx',
  '.epub',
  '.png',
  '.jpg',
  '.jpeg',
  '.webp',
] as const;

export const isSupportedUploadFileName = (fileName: string): boolean => {
  const extension = fileName.toLowerCase().slice(fileName.lastIndexOf('.'));
  return SUPPORTED_UPLOAD_FILE_EXTENSIONS.includes(
    extension as (typeof SUPPORTED_UPLOAD_FILE_EXTENSIONS)[number],
  );
};

export const getUploadFileError = (
  file: File,
  maxSizeMb: number,
  existingNames: string[],
): string | null => {
  if (!isSupportedUploadFileName(file.name)) {
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
