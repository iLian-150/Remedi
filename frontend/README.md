# Remedi 前端 MVP

Vue 3 + TypeScript + Vite + Vue Router + Pinia + ECharts + axios。

## 本地启动

```bash
cd ~/workspace/remedi/frontend
npm install        # 已安装过可跳过
npm run dev        # 默认 http://localhost:5173/
```

后端需先启动（FastAPI，默认 `http://localhost:8000`）。开发时 `/api` 由 Vite 代理到后端。

## 后端地址配置

复制 `.env` 按需修改（环境变量以 `VITE_` 开头）：

| 变量 | 说明 | 默认 |
|---|---|---|
| `VITE_API_BASE_URL` | API 基地址（留空则用相对路径 `/api`，走开发代理） | 空 |
| `VITE_BACKEND_TARGET` | 开发时代理目标（后端地址），仅 `VITE_API_BASE_URL` 为空时生效 | `http://localhost:8000` |

生产部署示例：`VITE_API_BASE_URL=https://api.example.com`，此时不再走代理。

## 目录结构（两端隔离，为拆分做准备）

```
src/
  views/student/   学生端页面：提交作业 / 批改结果 / 订正错题 / 错误档案
  views/teacher/   教师端页面：班级看板 / 批改列表 / 诊断详情 / 学生列表 / 学生画像
  stores/          auth.ts（登录态，Pinia+localStorage）/ student.ts / teacher.ts
  api/             client.ts（axios 统一封装，自动带 Authorization）/ types.ts（契约类型）
  components/      EChart.vue（ECharts 封装）
  router/          路由 + 守卫（未登录回登录页，角色不匹配跳各自首页）
```

## 契约对齐说明

严格按 `~/workspace/remedi/docs/api-contract.md` v0.1.0 实现。基于契约做的最小假设（详见汇报）：

1. 登录请求字段为 `{username, role}`（契约 2.1），无密码；用户不存在后端自动创建。
2. 数学提交后诊断**同步返回**（契约 3.3），前端在提交页直接展示分步诊断，无独立轮询。
3. 教师端批改列表按契约 4.1 错误记录列表实现（契约未提供教师端提交列表接口）。
4. 教师端诊断详情的 `:id` 按 error_id 解释：契约未提供单条 error 查询接口，前端取错误列表（limit 100）按 id 匹配；完整作答步骤链契约未对教师端开放，详情页仅展示出错步骤本身。
5. `/teacher/students`（学生列表）为契约 4.5 的导航页，任务路由清单未列出但进入学生画像必需。

演示账号：教师「陈老师」、学生「林小夏」「陈默」。
