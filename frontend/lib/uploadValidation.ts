const textLimitMessage = (maxCharacters: number): string =>
  `Text exceeds about ${maxCharacters.toLocaleString()} characters. `
    + 'Split it into smaller sources or ask your administrator to raise the '
    + 'per-source chunk limit.';

export const getTextContentError = (text: string, maxCharacters: number): string | null => {
  let characters = 0;
  const iterator = text[Symbol.iterator]();
  while (!iterator.next().done) {
    if (++characters > maxCharacters) return textLimitMessage(maxCharacters);
  }
  return null;
};

export const getUploadFileError = async (
  file: File,
  maxSizeMb: number,
  existingNames: string[],
  allowedFileTypes: string[],
  maxTextCharacters: number,
): Promise<string | null> => {
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

  if (['txt', 'md'].includes(extension)) {
    // shortcut: File.text decodes UTF-8; revisit if uploads gain configurable encodings.
    if (file.size > maxTextCharacters * 4) {
      return `${file.name}: ${textLimitMessage(maxTextCharacters)}`;
    }

    const error = getTextContentError(await file.text(), maxTextCharacters);
    if (error) return `${file.name}: ${error}`;
  }

  return null;
};
