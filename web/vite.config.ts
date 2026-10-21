import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react()],
  build: {
    target: "es2022",
    sourcemap: false,
    rolldownOptions: {
      output: {
        manualChunks(id) {
          if (
            id.includes("/node_modules/@codemirror/") ||
            id.includes("/node_modules/@lezer/")
          )
            return "editor";
          if (id.includes("/node_modules/ol/")) return "map";
          if (
            id.includes("/node_modules/motion") ||
            id.includes("/node_modules/framer-motion/")
          )
            return "motion";
          if (/\/node_modules\/(react|react-dom|scheduler)\//.test(id))
            return "react";
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/workbench": "http://localhost:8787",
      "/gee": "http://localhost:8787",
      "/openeo": "http://localhost:8787",
    },
  },
});
