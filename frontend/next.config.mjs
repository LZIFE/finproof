/** @type {import('next').NextConfig} */
const nextConfig = {
  // 将前端 /api/* 代理到本地 FastAPI 后端（默认 8000 端口）
  rewrites: async () => [
    { source: "/api/:path*", destination: "http://127.0.0.1:8000/:path*" },
  ],
};

export default nextConfig;
