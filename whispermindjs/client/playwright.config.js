module.exports = {
  testDir: './tests',
  reporter: 'line',
  use: {
    baseURL: process.env.WHISPERMIND_URL || 'http://127.0.0.1:5010',
    browserName: 'chromium',
    channel: 'chrome',
    headless: true,
    viewport: { width: 1280, height: 720 },
    launchOptions: {
      args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream'],
    },
  },
};
