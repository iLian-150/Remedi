# Remedi 前端

教师端和学生端共用的 Vue 3 + TypeScript 单页应用，使用 Vite、Vue Router、Pinia 和 Axios。页面、组件与样式须遵循[前端设计规范](../docs/frontend-design-guidelines.md)，接口以[当前 API 契约](../docs/api-contract.md)为准。

## 本地开发

```bash
cd frontend
npm ci
npm run dev
```

开发服务器默认运行在 `http://localhost:5173`。启动后端 FastAPI 服务，Vite 会将 `/api` 请求代理到后端。

## 配置

在 `frontend/.env` 中按需配置以下环境变量：

| 变量 | 说明 | 默认值 |
|---|---|---|
| `VITE_API_BASE_URL` | API 基地址；留空时使用相对路径 `/api` | 空 |
| `VITE_BACKEND_TARGET` | Vite 开发代理的后端地址 | `http://localhost:8000` |

不要把凭证或服务端密钥写入 `VITE_` 变量；这些变量会被打包到浏览器代码中。前端只通过本地 Vite 代理访问后端，不需要在浏览器中保存 API 密钥。

## 本地构建与验证

```bash
npm run build
```

构建产物输出到 `frontend/dist`，仅供本地预览或检查。本项目不在此流程中发布到服务器。

前端 smoke 脚本及后端验证入口见[验证说明](../docs/validation.md)。

## 页面与代码

- `src/views/student/`：学生端作业、错题、订正、学习档案与 AI 助手页面。
- `src/views/teacher/`：教师端总览、批改、学生、作业、资料与 AI 助手页面。
- `src/api/`：API 客户端和前后端数据类型。
- `src/stores/`：登录状态与页面数据状态。
- `src/router/`：路由和角色访问控制。

接口请求和响应、权限范围、异步任务行为及发布校验以 API 契约为准；不要依赖已过期的演示账号或旧接口假设。
