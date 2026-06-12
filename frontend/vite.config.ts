import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// https://vitejs.dev/config/
export default defineConfig(() => ({
  server: {
    host: "0.0.0.0", // Дозволяє відкривати сайт у локальній мережі
    port: 3000,      // Стандартний порт для фронтенду
    fs: {
      // Дозволяємо доступ лише до чистих папок фронтенду
      allow: ["./client", "./public", "index.html"],
      deny: [".env", ".env.*", "*.{crt,pem}", "**/.git/**"],
    },
  },
  build: {
    outDir: "dist", // Стандартна папка для релізної збірки HTML/JS/CSS
  },
  plugins: [react()],
  resolve: {
    alias: {
      // Налаштування коротких шляхів (аліасів) для імпортів
      "@": path.resolve(__dirname, "./client"),
    },
  },
}));
