import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: `npm run dev` proxies /api to the FastAPI server (uvicorn api:app on 127.0.0.1:8000).
// Prod: `npm run build` writes dist/, which api.py serves at / from the same server.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
