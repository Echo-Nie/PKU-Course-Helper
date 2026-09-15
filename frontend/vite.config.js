import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { viteSingleFile } from 'vite-plugin-singlefile';

export default defineConfig({ plugins: [react(), viteSingleFile(), {
  name: 'development-only-hmr-policy', apply: 'serve',
  transformIndexHtml(html) { return html.replace("connect-src 'none'", "connect-src 'self' ws://127.0.0.1:*"); },
}], build: { target: 'es2020', cssCodeSplit: false }, server: { host: '127.0.0.1' } });
