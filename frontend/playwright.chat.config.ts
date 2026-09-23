import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests', testMatch: 'chat-model.spec.ts',
  timeout: 30000, workers: 1, reporter: 'list',
  use: { channel: 'msedge', baseURL: 'http://127.0.0.1:5175', viewport: { width: 1440, height: 950 },
    launchOptions: { args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] } },
  webServer: { command: 'npm exec vite -- preview --host 127.0.0.1 --port 5175 --strictPort --outDir ../src/orion/server/static',
    url: 'http://127.0.0.1:5175', reuseExistingServer: false, timeout: 120000 },
});
