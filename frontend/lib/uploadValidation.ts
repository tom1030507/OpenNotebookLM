export const getUploadFileError = (
  file: File,
  maxSizeMb: number,
  existingNames: string[],
): string | null => {
  if (!file.name.toLowerCase().endsWith('.pdf')) {
    return `${file.name} 不是支援的 PDF 檔案`;
  }

  if (file.size > maxSizeMb * 1024 * 1024) {
    return `${file.name} 超過 ${maxSizeMb}MB 上限`;
  }

  if (existingNames.includes(file.name)) {
    return `${file.name} 已加入`;
  }

  return null;
};
