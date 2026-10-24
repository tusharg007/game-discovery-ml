import { defineConfig } from "vite";

export default defineConfig({
  base: "/static/",
  build: {
    outDir: "../src/game_discovery/web",
    emptyOutDir: true,
    rollupOptions: {
      output: {
        entryFileNames: "assets/app.js",
        assetFileNames: "assets/[name][extname]",
      },
    },
  },
});
