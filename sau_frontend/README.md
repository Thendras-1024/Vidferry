# Vidferry 前端控制台

本目录是 Vidferry 的 Vue 3 管理控制台，覆盖视频检索与处理、素材管理、文案、发布中心、账号管理、工作流状态和用户安全管理。

## 开发启动

先启动项目根目录的后端，再执行：

```powershell
npm install
npm run dev
```

Vite 默认监听 `http://127.0.0.1:55173` 并自动打开浏览器。开发服务器将：

- `/api` 代理到 `http://127.0.0.1:5409`，并移除 `/api` 前缀；
- `/accounts` 代理到 `http://127.0.0.1:5409`。

前端不保存 LLM 密钥、数据库连接串或平台 Cookie；这些配置只能留在后端根目录 `.env`。

## 构建与预览

```powershell
npm run build
npm run preview
```

构建结果输出到 `dist/`，仅用于部署静态控制台。生产环境应通过 HTTPS 反向代理访问后端，并遵循根目录 [认证与部署说明](../docs/deployment/用户认证与部署.md)。

## 相关文档

- [项目说明](../README.md)
- [快速部署](../docs/deployment/QUICK_DEPLOYMENT.md)
- [配置参考](../docs/deployment/CONFIGURATION.md)
