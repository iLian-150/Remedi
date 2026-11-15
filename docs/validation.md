# 本地验证入口

本项目只在本地开发与验证。按改动范围选择命令，不要默认运行会访问真实模型或服务的 smoke 脚本。

## 前端

在 `frontend/` 目录运行：

| 目的 | 命令 | 覆盖内容 |
| --- | --- | --- |
| 类型检查与构建 | `npm run build` | `vue-tsc --noEmit`、Vite 构建 |
| 逻辑 smoke | `npm run test:logic` | 登录、会话状态、资料导入任务 |

其他单页 smoke 脚本需单独运行：

```powershell
node scripts/smoke-student-image-submit.mjs
node scripts/smoke-recognized-math.mjs
node scripts/smoke-photo-stage.mjs
node scripts/smoke-assignment-navigation.mjs
```

## 后端

在仓库根目录创建的 `.venv` 中运行。PowerShell 示例：

```powershell
Set-Location backend
..\.venv\Scripts\python.exe smoke_health.py
```

按改动领域选择脚本：

| 领域 | 脚本 |
| --- | --- |
| 作业与教学计划 | `smoke_assignment_edit.py`、`smoke_assignment_answer_upload.py`、`smoke_teacher_assignment_detail.py`、`smoke_teaching_plan.py` |
| 批改、审核与关注名单 | `smoke_scoring.py`、`smoke_review_flow.py`、`smoke_review_concurrency.py`、`smoke_verification_concurrency.py`、`smoke_teacher_attention.py` |
| Agent、偏好与会话 | `smoke_agent_tool_execution.py`、`smoke_assistant_preferences.py`、`smoke_chat_sessions.py`、`smoke_process_check.py` |
| 资料导入与检索 | `smoke_subject_rag.py`、`smoke_rag_quality.py`、`smoke_rag_milvus.py`、`smoke_knowledge_api.py`、`smoke_knowledge_import.py`、`smoke_knowledge_jobs.py`、`smoke_import_index_status.py`、`smoke_diagram_jobs.py` |
| 模型供应商 | `smoke_bailian.py`、`smoke_bailian_rerank.py` |
| 本地服务健康 | `smoke_health.py` |
| 真实链路 | `smoke_live_rag.py` |

`smoke_rag_milvus.py` 使用替身拦截网络，不连接真实 Milvus 或百炼；`smoke_live_rag.py` 会访问实际服务并创建、清理临时资料。真实链路脚本需确认本地服务、环境变量和测试数据条件后再运行。

## 常用代码入口

| 区域 | 入口 |
| --- | --- |
| 全局导航和页面标题 | `frontend/src/App.vue`、`frontend/src/router/index.ts` |
| 教师 AI 批改 | `/teacher/submissions` → `frontend/src/views/teacher/TeacherAIGradings.vue` |
| 教师资料 | `/teacher/materials` → `frontend/src/views/teacher/TeacherKnowledge.vue` |
| 作业发布 | `frontend/src/views/teacher/TeacherPublish.vue` |
| 学生订正与报告 | `frontend/src/views/student/StudentCorrections.vue`、`frontend/src/views/student/StudentReportSubject.vue` |
| 教师和学生 API | `backend/app/routers/teacher.py`、`backend/app/routers/student.py` |

`/teacher/reviews` 与 `/teacher/workbooks` 是兼容重定向，不再对应独立页面。修改页面前先从路由确认当前组件，避免改到未挂载的旧实现。
