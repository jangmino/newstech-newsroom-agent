import { startVitest } from "vitest/node";
import react from "@vitejs/plugin-react";

// Pass envFile as a Vite inline option: a config-file property does not disable dotenv.
// No dev-server config, proxy, credentials, or provider calls are used in UI tests.
await startVitest("test", process.argv.slice(2), {
  run: true,
  environment: "jsdom",
  include: ["src/**/*.test.tsx"],
  setupFiles: ["./src/test/setup.ts"],
  restoreMocks: true,
  unstubGlobals: true,
}, {
  configFile: false,
  envFile: false,
  plugins: [react()],
});
