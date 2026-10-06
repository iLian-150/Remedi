# Remedi MVP 接口契约（API Contract）

> 版本：v0.2.0（2026-10-07）
> **契约冻结声明**：本文档是前后端联调的唯一依据。接口一旦写入本文档即视为冻结，任何 breaking 变更（改路径、改字段名、改必填性、改枚举值）必须先更新本文档并同步通知 frontend worker。新增非 breaking 字段允许，但必须在文档中标注。

## 1. 基础约定

- **Base URL**：`http://localhost:8000`
- **命名空间**：
  - `/api/auth/*` —— 登录与身份
  - `/api/student/*` —— 学生端（需学生身份）
  - `/api/teacher/*` —— 教师端（需教师身份）
  - `/api/health` —— 健康检查（无需登录）
- **数据格式**：请求与响应均为 `application/json; charset=utf-8`。
- **时间格式**：ISO 8601，如 `2026-10-06T15:40:35`（本地时间，不带时区后缀）。
- **分页**：列表接口统一用 `limit`（默认 20，最大 100）、`offset`（默认 0），响应形如 `{"total": 42, "items": [...]}`。

### 1.1 认证方式（Mock 登录）

MVP 阶段使用最简 mock 登录，不设密码，仅用于演示与联调：

1. `POST /api/auth/login` 传入 `{"username": "林小夏", "role": "student"}`。
2. 后端按 `username + role` 查找用户；**不存在则自动创建**（学生自动生成学号 `Sxxxx`，教师学号为空）。
3. 返回 `token`，后续请求在 Header 中携带：`Authorization: Bearer <token>`。
4. token 格式为 `mock-<user_id>`（纯演示用，生产环境必须替换为 JWT）。

角色校验：`/api/student/*` 只允许 `role=student` 且只能操作自己的数据；`/api/teacher/*` 只允许 `role=teacher`。

### 1.2 通用错误响应

所有错误响应体统一为：

```json
{ "detail": "错误描述（中文）" }
```

| HTTP 状态码 | 含义 | 典型场景 |
|---|---|---|
| 400 | 请求错误 | 业务规则不满足（如给作文题调了数学诊断接口） |
| 401 | 未认证 | 缺少/无效 token |
| 403 | 无权限 | 学生调教师接口、越权访问他人数据 |
| 404 | 不存在 | id 查无记录 |
| 422 | 参数校验失败 | 字段缺失、类型错误、steps 为空等 |
| 500 | 服务内部错误 | 诊断/LLM 异常（已做降级，极少出现） |

---

## 2. /api/auth/* —— 登录与身份

### 2.1 POST /api/auth/login —— mock 登录

权限：无需登录。

请求：

```json
{
  "username": "林小夏",
  "role": "student"
}
```

- `username`: string，必填，用户名（演示数据：教师 `陈老师` / 学生 `林小夏` / `陈默`）。
- `role`: string，必填，枚举 `teacher | student`。

响应 `200`：

```json
{
  "token": "mock-2",
  "token_type": "bearer",
  "user": {
    "id": 2,
    "name": "林小夏",
    "student_no": "S2026001",
    "role": "student"
  }
}
```

错误：`422` 参数缺失/role 非法。

### 2.2 GET /api/auth/me —— 当前登录用户

权限：需 Bearer token。

响应 `200`：

```json
{
  "id": 2,
  "name": "林小夏",
  "student_no": "S2026001",
  "role": "student"
}
```

错误：`401` token 缺失或无效。

---

## 3. /api/student/* —— 学生端

### 3.1 GET /api/student/assignments —— 作业列表

权限：学生。

响应 `200`：

```json
{
  "total": 1,
  "items": [
    {
      "id": 1,
      "title": "第一周数学+英语作业",
      "description": "包含 3 道数学题与 1 篇英语作文",
      "question_count": 4,
      "created_at": "2026-10-06T10:00:00"
    }
  ]
}
```

### 3.2 GET /api/student/assignments/{assignment_id} —— 作业详情（含题目）

权限：学生。

响应 `200`（注意：**不返回标准答案**）：

```json
{
  "id": 1,
  "title": "第一周数学+英语作业",
  "description": "包含 3 道数学题与 1 篇英语作文",
  "questions": [
    {
      "id": 1,
      "subject": "math",
      "knowledge_point": "一元一次方程",
      "stem": "解方程：2x+3=7",
      "order_num": 1
    },
    {
      "id": 4,
      "subject": "english",
      "knowledge_point": "英语写作",
      "stem": "Write a short paragraph about your weekend (60-80 words).",
      "order_num": 4
    }
  ]
}
```

错误：`404` 作业不存在。

### 3.3 POST /api/student/submissions —— 提交数学作业并诊断 ⭐核心接口

权限：学生。

**提交约定**：`steps` 只传学生的作答步骤（按顺序），**不要传题干**；后端自动把题干作为 `seq=0` 的步骤存入。

请求：

```json
{
  "question_id": 1,
  "steps": ["2x+3=7", "2x=7+3", "2x=10", "x=5"]
}
```

- `question_id`: int，必填，必须是 `subject=math` 的题目。
- `steps`: string[]，必填，1~20 个步骤，每个步骤最多 500 字符。

响应 `200`（诊断在请求内同步完成）：

```json
{
  "submission_id": 7,
  "question_id": 1,
  "status": "graded",
  "first_error_seq": 1,
  "steps": [
    {"seq": 0, "text": "解方程：2x+3=7", "status": "stem"},
    {"seq": 1, "text": "2x=7+3", "status": "error"},
    {"seq": 2, "text": "2x=10", "status": "skipped"},
    {"seq": 3, "text": "x=5", "status": "skipped"}
  ],
  "errors": [
    {
      "id": 9,
      "submission_id": 7,
      "step_seq": 1,
      "step_text": "2x=7+3",
      "knowledge_point": "一元一次方程",
      "error_type": "概念混淆",
      "confidence": 0.85,
      "is_stubborn": true,
      "detail": "移项未变号：+3 移到等号右边应变为 −3，正确变形应为 2x=7−3",
      "teacher_corrected": false,
      "teacher_note": null,
      "created_at": "2026-10-06T15:45:00"
    }
  ]
}
```

字段说明：

- `status`: `graded`（已诊断）。若全对，`errors` 为空数组，`first_error_seq` 为 `null`。
- `first_error_seq`：首个真正不等价（`status=error`）步骤的 seq；若本次只有 `无法解析` 而无不等价步骤，则指向首个无法解析步骤的 seq。
- `steps[].status` 枚举：`stem`（题干，仅参考）| `ok`（与上一步等价）| `error`（首次不等价，出错位置）| `unparseable`（无法解析，已记为一条低置信度 error，流程继续）| `skipped`（首次出错之后的步骤不再校验）。
- `errors[].error_type` 枚举：`计算失误` | `概念混淆` | `审题遗漏` | `无法解析`。
- `errors[].confidence`：0~1。规则命中概念误区 0.85 / 算术小偏差 0.7 / 兜底 0.5 / 无法解析 0.3。
- `errors[].is_stubborn`：该生该知识点近 N 天（默认 30 天，可配 `STUBBORN_WINDOW_DAYS`）内再次出错即为 `true`（顽固误区），否则为偶发失误。

错误：`400`（题目是作文题，请用 `/api/student/essays`）、`404`（题目不存在）、`422`（steps 为空/超限）。

### 3.4 GET /api/student/submissions —— 我的提交记录

权限：学生。支持 `?question_id=` 过滤。

响应 `200`：

```json
{
  "total": 2,
  "items": [
    {
      "id": 7,
      "question_id": 1,
      "question_stem": "解方程：2x+3=7",
      "knowledge_point": "一元一次方程",
      "status": "graded",
      "error_count": 1,
      "submitted_at": "2026-10-06T15:45:00"
    }
  ]
}
```

### 3.5 GET /api/student/submissions/{submission_id} —— 提交详情

权限：学生（只能看自己的）。

响应 `200`：结构同 3.3 的响应体（submission_id/question_id/status/first_error_seq/steps/errors）。

错误：`403` 不是本人的提交；`404` 不存在。

### 3.6 POST /api/student/essays —— 提交英语作文并评分 ⭐

权限：学生。

请求：

```json
{
  "question_id": 4,
  "text": "Last weekend was very fun. I go to the park with my friend. He like playing football..."
}
```

- `question_id`: int，选填，关联的作文题（可为空）。
- `text`: string，必填，作文原文（10~2000 字符）。

响应 `200`：

```json
{
  "essay_id": 3,
  "scores": {
    "content": 78,
    "structure": 70,
    "grammar": 64,
    "vocabulary": 72,
    "expression": 70,
    "total": 71
  },
  "grammar_issues": [
    {
      "sentence_no": 2,
      "sentence": "I go to the park with my friend.",
      "issue": "时态/主谓一致：go 前的主语是 I，此处疑似想表达过去时",
      "suggestion": "改为 went（last weekend 为过去时间）"
    },
    {
      "sentence_no": 3,
      "sentence": "He like playing football.",
      "issue": "第三人称单数动词未加 -s",
      "suggestion": "like → likes"
    }
  ],
  "overall": "内容完整，能围绕周末活动展开；注意过去时态的一致性与第三人称单数动词形式。建议多使用连接词提升结构分。",
  "submitted_at": "2026-10-06T15:50:00"
}
```

- 五维分数均为 0~100 整数：`content` 内容 / `structure` 结构 / `grammar` 语法 / `vocabulary` 词汇 / `expression` 表达；`total` 为五维均值（四舍五入）。
- `grammar_issues` 按句子定位，`sentence_no` 从 1 开始。

错误：`422`（text 为空/超长）；`404`（question_id 不存在）。

### 3.7 GET /api/student/essays —— 我的作文列表

权限：学生。响应 `200`：`{"total": n, "items": [{"essay_id": 3, "question_id": 4, "total": 71, "submitted_at": "..."}]}`。

### 3.8 GET /api/student/essays/{essay_id} —— 作文详情

权限：学生（只能看自己的）。响应 `200`：结构同 3.6，另含 `text` 原文与 `question_id`。

### 3.9 POST /api/student/corrections —— 提交订正

权限：学生。针对某条 error 提交订正内容，后端用 sympy 自动判定正误。

请求：

```json
{
  "error_id": 9,
  "content": "2x=7-3"
}
```

响应 `200`：

```json
{
  "id": 3,
  "error_id": 9,
  "content": "2x=7-3",
  "is_correct": true,
  "note": "订正步骤与出错前一步等价，订正正确",
  "submitted_at": "2026-10-06T16:00:00"
}
```

- `is_correct`：`true` 正确 / `false` 仍不正确 / `null` 无法判定（订正内容无法解析或非数学题，需教师确认）。

错误：`403`（该 error 不属于本人）；`404`（error 不存在）。

### 3.10 GET /api/student/profile —— 我的学习画像

权限：学生。

响应 `200`：

```json
{
  "student": {"id": 2, "name": "林小夏", "student_no": "S2026001"},
  "knowledge_points": [
    {
      "knowledge_point": "一元一次方程",
      "attempts": 3,
      "errors": 2,
      "error_rate": 0.667,
      "mastery": 0.333
    }
  ],
  "stubborn_errors": [
    {
      "id": 9,
      "knowledge_point": "一元一次方程",
      "error_type": "概念混淆",
      "step_text": "2x=7+3",
      "created_at": "2026-10-06T15:45:00"
    }
  ],
  "recent_errors": ["...同上结构，最多 5 条..."],
  "suggestion": "你在「一元一次方程」上存在顽固误区（30 天内重复出错 2 次），主要问题是移项变号规则。建议先重看移项规则，再做 3 道针对性练习。"
}
```

- `error_rate = errors / attempts`（保留 3 位小数，上限截断为 1.0——一次提交可能产生多条 error）；`mastery = 1 - error_rate`。
- `attempts`：该知识点题目的提交次数；`errors`：该知识点累计 error 记录数。
- `suggestion`：由 LLM Provider 生成（Mock 为确定性模板，无需 key）。

### 3.11 POST /api/student/photo-transcribe —— 拍照转写作业 ⭐（v0.2.0 新增）

权限：学生。

请求：`multipart/form-data`，字段 `file` 为作业照片（jpg / png / webp，≤10MB）。

响应 `200`：

```json
{
  "image_id": "20261007103000_a1b2c3d4.png",
  "image_url": "/uploads/20261007103000_a1b2c3d4.png",
  "question_text": "解方程：2x+3=7",
  "steps": ["2x+3=7", "2x=7+3", "2x=10", "x=5"]
}
```

- `question_text`：转写出的题干；`steps`：学生作答步骤（按顺序，**不含题干**）。
- 图片只存服务器本地目录（环境变量 `UPLOAD_DIR`，默认 `backend/uploads/`），不落库；`image_url` 为静态回读路径。
- 转写由当前 LLM Provider 的视觉能力完成：Cloudflare 走视觉模型 `@cf/meta/llama-3.2-11b-vision-instruct`（可用 `CLOUDFLARE_VISION_MODEL` 覆盖）；Mock / 无凭证 / 识别异常时降级为确定性罐头转写，保证流程不中断。
- 本接口**不产生提交记录**：学生确认/编辑转写结果后，仍走 3.3 `POST /api/student/submissions`（question_id + steps）完成诊断。

错误：`400`（格式不支持 / 内容为空 / 超过 10MB，detail 为中文说明）；`403`（教师调用学生接口）。

### 3.12 GET /api/student/briefing —— 首页待办简报（v0.2.0 新增）

权限：学生。对话页打开时播报的数据来源，全部由现有表拼装，不调 LLM。

响应 `200`：

```json
{
  "pending_assignments": [
    {"id": 1, "title": "第一周数学+英语作业", "question_count": 4, "remaining_count": 3, "created_at": "2026-10-06T10:00:00"}
  ],
  "pending_corrections_count": 1,
  "pending_corrections_knowledge_points": ["一元一次方程"],
  "weak_points": ["一元一次方程"],
  "recent_feedback": "最近一次批改《解方程：2x+3=7》：移项未变号：3 移到等号另一边时没有变号"
}
```

- `pending_assignments`：至少有一道题该生未提交过的作业（数学题以 submissions 计、作文题以 essays 计）；`remaining_count` 为未提交题目数。
- `pending_corrections_*`：本人 error 中尚无一条 `is_correct=true` 订正记录的条数，及涉及知识点（去重）。
- `weak_points`：需要加固的知识点 = 顽固误区涉及的知识点 ∪ 错误率 ≥ 50% 的知识点（聚合口径同 3.10）。
- `recent_feedback`：最近一次数学批改的一句话摘要（有错取引首条 error 的 detail，全对则为鼓励语）；从未提交过时为 `null`。

---

## 4. /api/teacher/* —— 教师端

### 4.1 GET /api/teacher/errors —— 错误记录列表

权限：教师。支持过滤：`student_id` / `knowledge_point` / `error_type` / `stubborn_only=true`，以及 `limit` / `offset`。

响应 `200`：

```json
{
  "total": 3,
  "items": [
    {
      "id": 9,
      "student": {"id": 2, "name": "林小夏", "student_no": "S2026001"},
      "question": {"id": 1, "stem": "解方程：2x+3=7", "subject": "math"},
      "step_seq": 1,
      "step_text": "2x=7+3",
      "knowledge_point": "一元一次方程",
      "error_type": "概念混淆",
      "confidence": 0.85,
      "is_stubborn": true,
      "detail": "移项未变号：+3 移到等号右边应变为 −3",
      "teacher_corrected": false,
      "teacher_note": null,
      "created_at": "2026-10-06T15:45:00"
    }
  ]
}
```

### 4.2 POST /api/teacher/errors/{error_id}/correct —— 教师一键纠错 ⭐

权限：教师。修正某条 error 的分类并写备注，置 `teacher_corrected=true`（回标数据入库，用于后续模型优化）。

请求：

```json
{
  "error_type": "计算失误",
  "teacher_note": "经核实是抄错数字，移项规则本身掌握没问题"
}
```

- `error_type`：必填，枚举 `计算失误 | 概念混淆 | 审题遗漏 | 无法解析`。
- `teacher_note`：选填，备注。

响应 `200`：返回更新后的完整 error 对象（结构同 4.1 的 item，`teacher_corrected=true`）。

错误：`404` error 不存在；`422` error_type 非法。

### 4.3 GET /api/teacher/stats/top-questions —— 高频错题 TopN

权限：教师。`?n=10`（默认 10，最大 50）。

响应 `200`（供 ECharts 柱状图直接使用）：

```json
{
  "n": 10,
  "items": [
    {
      "question_id": 1,
      "stem": "解方程：2x+3=7",
      "subject": "math",
      "knowledge_point": "一元一次方程",
      "error_count": 4,
      "student_count": 2
    }
  ]
}
```

按 `error_count` 降序。

### 4.4 GET /api/teacher/stats/knowledge-points —— 知识点错误率排行

权限：教师。

响应 `200`：

```json
{
  "items": [
    {
      "knowledge_point": "一元一次方程",
      "submissions": 6,
      "errors": 4,
      "error_rate": 0.667
    }
  ]
}
```

- 口径：`submissions` = 该知识点题目的提交总数；`errors` = 该知识点累计 error 数；`error_rate = errors / submissions`（保留 3 位小数，上限截断为 1.0——一次提交可能产生多条 error）。按 `error_rate` 降序。

### 4.5 GET /api/teacher/students —— 学生列表

权限：教师。

响应 `200`：

```json
{
  "total": 2,
  "items": [
    {
      "id": 2,
      "name": "林小夏",
      "student_no": "S2026001",
      "submission_count": 3,
      "error_count": 2
    }
  ]
}
```

### 4.6 GET /api/teacher/students/{student_id}/profile —— 学生画像查询

权限：教师。响应结构同 3.10（`student` 为目标学生）。

### 4.7 POST /api/teacher/assignments —— 发布作业（v0.2.0 新增）

权限：教师。创建一份作业并落库，学生端立即可见（3.1 / 3.2）。

请求：

```json
{
  "title": "第二周数学作业",
  "subject": "math",
  "description": "选填说明",
  "questions": [
    {
      "type": "math",
      "prompt": "解方程：3x-5=10",
      "knowledge_point": "一元一次方程",
      "standard_steps": ["3x-5=10", "3x=10+5", "3x=15", "x=5"],
      "reference_answer": "x=5"
    }
  ]
}
```

- `subject`：选填，作业级学科标记（`math | english`），仅记录用；题目学科以每题 `type` 为准。
- `questions[].type`：`math | essay`，分别落库为题目 `subject=math | english`；`prompt` 落库为题干 `stem`；`order_num` 按数组顺序从 1 开始。
- `standard_steps` / `reference_answer`：选填，仅教师可见（学生端详情不返回标准答案，沿用 3.2 约定）。`standard_steps` 无独立存储列：当 `reference_answer` 为空时，它按行拼入 `standard_answer` 字段保存。
- 校验：`questions` 至少 1 道；`title` / `prompt` / `knowledge_point` 非空，否则 `422`。

响应 `200`：

```json
{
  "id": 2,
  "title": "第二周数学作业",
  "description": null,
  "created_at": "2026-10-07T10:30:00",
  "questions": [
    {
      "id": 5,
      "type": "math",
      "prompt": "解方程：3x-5=10",
      "knowledge_point": "一元一次方程",
      "standard_answer": "x=5",
      "submission_count": 0
    }
  ]
}
```

### 4.8 GET /api/teacher/assignments —— 已发布作业列表（v0.2.0 新增）

权限：教师。响应 `200`：`{"total": n, "items": [...]}`，item 结构同 4.7 响应。

- `submission_count`：该题的累计提交记录数（submissions + essays，同一学生多次提交计多次）。

---

## 5. /api/health —— 健康检查

### 5.1 GET /api/health

权限：无需登录。

响应 `200`：

```json
{
  "status": "ok",
  "version": "0.2.0",
  "provider": "mock",
  "time": "2026-10-06T15:40:35"
}
```

- `provider`：当前 LLM Provider（`mock` | `deepseek` | `cloudflare`）。

---

## 6. 枚举值总览（前端写死下拉框用）

| 字段 | 枚举值 |
|---|---|
| `role` | `teacher` / `student` |
| `subject` | `math` / `english` |
| `error_type` | `计算失误` / `概念混淆` / `审题遗漏` / `无法解析` |
| `step.status` | `stem` / `ok` / `error` / `unparseable` / `skipped` |
| `submission.status` | `submitted` / `graded` |

## 7. 变更记录

| 版本 | 日期 | 说明 |
|---|---|---|
| v0.1.0 | 2026-10-06 | 初版冻结 |
| v0.2.0 | 2026-10-07 | 新增 3.11 拍照转写、3.12 首页简报、4.7 发布作业、4.8 教师作业列表；无 breaking 变更 |
