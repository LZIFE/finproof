/** @type {import('next').NextConfig} */
const nextConfig = {
  // 将前端 /api/* 代理到本地 FastAPI 后端（默认 8000 端口）
  // 注意：后端路由以 /api/v1/... 为前缀，故 destination 保留 /api 段
  rewrites: async () => [
    { source: "/api/:path*", destination: "http://127.0.0.1:8000/api/:path*" },
  ],
};

export default nextConfig;
