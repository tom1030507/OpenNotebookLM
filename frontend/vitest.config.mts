import { fileURLToPath, URL } from 'node:url';

import { defineConfig } from 'vitest/config';


export default defineConfig({
  oxc: {
    jsx: 'react-jsx',
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('.', import.meta.url)),
    },
  },
});
