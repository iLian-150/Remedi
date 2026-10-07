# Remedi MVP 接口契约（API Contract）

> 版本：v0.4.0（2026-10-07）
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
      "title": "第一周数学作业",
      "description": "包含 3 道数学题",
      "question_count": 3,
      "created_at": "2026-10-06T10:00:00"
    }
  ]
}
```

- `created_at`：作业发布时间（ISO 8601），学生/教师两端作业日历的数据源（v0.2.1 确认双端均有此字段，无变更）。

### 3.2 GET /api/student/assignments/{assignment_id} —— 作业详情（含题目）

权限：学生。

响应 `200`（注意：**不返回标准答案**）：

```json
{
  "id": 1,
  "title": "第一周数学作业",
  "description": "包含 3 道数学题",
  "questions": [
    {
      "id": 1,
      "subject": "math",
      "knowledge_point": "一元一次方程",
      "stem": "解方程：2x+3=7",
      "order_num": 1
    },
    {
      "id": 3,
      "subject": "math",
      "knowledge_point": "去括号",
      "stem": "解方程：2(x-3)=10",
      "order_num": 3
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
  ],
  "follow_up_question": "把 +3 从等号左边拿走时，右边要做什么，天平才不会倾斜？"
}
```

字段说明：

- `status`: `graded`（已诊断）。若全对，`errors` 为空数组，`first_error_seq` 为 `null`。
- `first_error_seq`：首个真正不等价（`status=error`）步骤的 seq；若本次只有 `无法解析` 而无不等价步骤，则指向首个无法解析步骤的 seq。
- `steps[].status` 枚举：`stem`（题干，仅参考）| `ok`（与上一步等价）| `error`（首次不等价，出错位置）| `unparseable`（无法解析，已记为一条低置信度 error，流程继续）| `skipped`（首次出错之后的步骤不再校验）。
- `errors[].error_type` 枚举：`计算失误` | `概念混淆` | `审题遗漏` | `无法解析`。
- `errors[].confidence`：0~1。规则命中概念误区 0.85 / 算术小偏差 0.7 / 兜底 0.5 / 无法解析 0.3。
- `errors[].is_stubborn`：该生该知识点近 N 天（默认 30 天，可配 `STUBBORN_WINDOW_DAYS`）内再次出错即为 `true`（顽固误区），否则为偶发失误。
- `follow_up_question`（v0.4.0 新增）：按主错因（与 `first_error_seq` 同口径）+ 知识点由模板生成的一句启发式追问，引导学生先自己想明白错在哪；全对（`errors` 为空）时为 `null`。GET 3.5 提交详情同结构，同样带此字段。

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
  "submitted_at": "2026-10-06T16:00:00",
  "can_verify": true,
  "knowledge_point": "一元一次方程"
}
```

- `is_correct`：`true` 正确 / `false` 仍不正确 / `null` 无法判定（订正内容无法解析或非数学题，需教师确认）。
- `can_verify`（v0.4.0 新增，只加字段）：订正成功（`is_correct=true`）时为 `true`，提示前端引导学生去做二次验证（3.19）；其余情况为 `false`。
- `knowledge_point`（v0.4.0 新增，只加字段）：该条错题所属知识点，供前端直达对应知识点的验证。

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
    {"id": 1, "title": "第一周数学作业", "question_count": 3, "remaining_count": 2, "created_at": "2026-10-06T10:00:00"}
  ],
  "pending_corrections_count": 1,
  "pending_corrections_knowledge_points": ["一元一次方程"],
  "weak_points": ["一元一次方程"],
  "weak_point_details": [
    {"knowledge_point": "一元一次方程", "error_count": 2, "last_error_at": "2026-10-06T15:45:00"}
  ],
  "recent_feedback": "最近一次批改《解方程：2x+3=7》：移项未变号：3 移到等号另一边时没有变号"
}
```

- `pending_assignments`：至少有一道题该生未提交过的作业（数学题以 submissions 计、作文题以 essays 计）；`remaining_count` 为未提交题目数。
- `pending_corrections_*`：本人 error 中尚无一条 `is_correct=true` 订正记录的条数，及涉及知识点（去重）。
- `weak_points`：需要加固的知识点 = 顽固误区涉及的知识点 ∪ 错误率 ≥ 50% 的知识点（聚合口径同 3.10）。
- `weak_point_details`（v0.2.1 新增，非 breaking）：与 `weak_points` 同序的明细，供简报卡片展示每个知识点的累计出错次数与最近出错时间。
- `recent_feedback`：最近一次数学批改的一句话摘要（有错取引首条 error 的 detail，全对则为鼓励语）；从未提交过时为 `null`。

### 3.13 GET /api/student/report —— 我的学习报告（v0.2.1 新增）

权限：学生。对应开题报告「学习记忆层 + 教学反馈层」的学生侧报告：科目 → 知识点 → 错题时间线（3.14） → 步骤诊断（3.5）四级下钻。本接口返回前两级。

响应 `200`（顶层为数组，每个元素是一个科目）：

```json
[
  {
    "subject": "math",
    "submission_count": 6,
    "correct_rate": 0.667,
    "pending_fix_count": 1,
    "fixed_ratio": 0.5,
    "knowledge_points": [
      {
        "name": "一元一次方程",
        "attempts": 3,
        "error_count": 2,
        "error_rate": 0.667,
        "status": "stubborn",
        "last_error_at": "2026-10-06T15:45:00"
      }
    ]
  }
]
```

- `correct_rate`：`1 - error_rate`，错误率口径与 3.10 学生画像一致（该科目累计 error 数 / 提交数，上限截断 1.0）。
- `knowledge_points`：仅包含出过错的知识点，按 `error_rate` 降序。
- `status` 口径（**v0.4.0 升级为四态**）：
  - `fixed`（已修复）= 该生已**通过该知识点的二次验证**（3.19 创建、3.21 判定通过）；
  - `awaiting_verify`（已订正待验证）= 该知识点每条错题都已有 `is_correct=true` 的订正，但尚未通过二次验证；
  - `stubborn`（反复出错）= 命中既有顽固判定（该知识点任一错题 `is_stubborn=true`，即诊断时同知识点在窗口天数内重复出错），且仍有未订正错题；
  - `pending`（待修复）= 其余有未订正错题的情况。
- **口径变更说明**：v0.3 及以前「错题全部订正即 `fixed`」的口径自 v0.4.0 起废弃——订正只证明这一步改对了，必须再独立做对一道同知识点变式题（二次验证）才算修复。受影响的既有字段仅语义收紧，字段名与类型不变：`status` 新增枚举值 `awaiting_verify`（前端需兼容四态），`fixed_ratio` 数值会因新口径下降。
- `pending_fix_count`：`status != fixed` 的知识点数；`fixed_ratio` 即**知识修复率** = `fixed` 知识点数 / 出过错的知识点数（无出过错知识点时为 1.0）。

### 3.14 GET /api/student/report/knowledge-points/{name}/errors —— 知识点错题时间线（v0.2.1 新增）

权限：学生。`{name}` 为知识点名称（URL 编码）。返回该生在该知识点下的全部错题，按时间倒序——即纵向学习记忆的时间线。

响应 `200`：

```json
[
  {
    "created_at": "2026-10-06T15:45:00",
    "assignment_title": "第一周数学作业",
    "question_prompt": "解方程：2x+3=7",
    "first_error_seq": 2,
    "error_type": "概念混淆",
    "corrected": false,
    "submission_id": 7
  }
]
```

- `first_error_seq`：该条错题所在步骤的序号（与 3.3 诊断中的 `step_seq` 同口径）；无关联步骤时为 `null`。
- `corrected`：该条错题是否已有 `is_correct=true` 的订正。
- 点某条可凭 `submission_id` 跳 3.5 查看步骤级诊断。

### 3.15 POST /api/student/agent/chat —— 与学习助手对话（v0.3.0 新增）

权限：学生。学生主页的交互 Agent（LangGraph 状态图：LLM 节点 + 工具节点），可自由聊数学知识、答疑，并能调用工具查本人待办/学习报告/知识点错题（身份由后端注入，模型不能指定他人）。判分仍走 3.3 的确定性管线，Agent 不参与判分。

请求：

```json
{ "message": "我哪个知识点最需要加固？" }
```

- `message`：必填，单条最长 2000 字，超限返回 `400`（detail 为中文提示）。

响应 `200`：

```json
{ "reply": "你目前最需要加固的是「一元一次方程」……" }
```

- 后端取该生最近 20 条对话（3.16 的表）组上下文，本次的用户消息与助手回复都会落库。
- LLM 走与 Provider 层同一套配置（`LLM_PROVIDER=cloudflare|deepseek` 时用对应 OpenAI 兼容端点）；mock、无凭证或模型调用异常时自动降级为规则回复（关键词路由到真实的简报/报告/时间线数据拼模板），接口不返回 500。

### 3.16 GET /api/student/agent/history —— 我的对话历史（v0.3.0 新增）

权限：学生。返回最近 50 条对话，时间正序（旧 → 新），供主页对话页回放。

响应 `200`：

```json
[
  {"role": "user", "content": "移项为什么要变号", "created_at": "2026-10-07T10:00:00"},
  {"role": "assistant", "content": "方程其实就是一架天平……", "created_at": "2026-10-07T10:00:05"}
]
```

- `role` 枚举：`user` | `assistant`。

### 3.17 GET /api/student/notifications —— 我的提醒列表（v0.3.0 新增）

权限：学生。右侧栏提醒区的数据源：最近 30 条，按时间倒序（新 → 旧）。

响应 `200`：

```json
{
  "unread_count": 1,
  "items": [
    {
      "id": 5,
      "type": "teacher_correction",
      "content": "陈老师调整了你《第一周数学作业》的批改结果：错因由概念混淆改为计算失误，点开看看老师的复核结果吧。",
      "related_submission_id": 7,
      "is_read": false,
      "created_at": "2026-10-07T11:00:00"
    }
  ]
}
```

- `type` 目前只有 `teacher_correction`（教师一键纠错后生成，见 4.2）；`related_submission_id` 点提醒跳诊断报告时用，可为 `null`。

### 3.18 POST /api/student/notifications/read —— 提醒标已读（v0.3.0 新增）

权限：学生。

请求：`{ "ids": [5] }` —— `ids` 选填，不传或为空数组表示全部标已读；传入时只标本人的这些条。

响应 `200`：`{ "updated": 1, "unread_count": 0 }`。

### 3.19 POST /api/student/verifications —— 创建二次验证（变式题）（v0.4.0 新增）⭐

权限：学生。闭环的「验证」一环：为某知识点生成一道**变式题**（同知识点、换数字/情境的新题），学生独立做对才算该知识点修复（见 3.13 状态口径）。

请求：

```json
{ "knowledge_point": "一元一次方程", "source_error_id": 9 }
```

- `knowledge_point`：必填。
- `source_error_id`：选填，触发本次验证的错题 id（必须属于本人，否则 `400`）；不传时后端默认取该生该知识点最近一条错题，可为空。

行为：

- 该知识点已有未完成的验证（`status=pending`）时**直接复用**返回，不重复出题；已有 `failed` 记录的不复用，重新生成新题（即「换一道题重试」走本接口再调一次）。
- 出题方式：优先参数化模板（系数随机，标准步骤与答案由 sympy 验算）——覆盖 `一元一次方程`（ax+b=c 型）、`完全平方公式`（展开）、`去括号` / `去括号与合并同类项`；无模板的知识点走 Provider 兜底生成同类题，生成结果能通过 sympy 逐步验算的按严格模式判定，不能的标为练习模式（仍可走 3.21 的步骤诊断判定）。

响应 `200`（**只下发题干，答案与标准步骤永不下发**）：

```json
{
  "id": 1,
  "knowledge_point": "一元一次方程",
  "prompt": "解方程：6x+2=44",
  "status": "pending",
  "attempts": 0,
  "source_error_id": 9,
  "created_at": "2026-10-07T10:00:00",
  "completed_at": null
}
```

错误：`400`（`source_error_id` 不是本人的错题）、`422`（`knowledge_point` 为空）。

### 3.20 GET /api/student/verifications —— 我的验证列表（v0.4.0 新增）

权限：学生。返回本人最近 50 条验证记录（时间倒序），元素结构同 3.19 响应（含 `status`：`pending` | `passed` | `failed`）。

### 3.21 POST /api/student/verifications/{id}/submit —— 提交验证作答（v0.4.0 新增）⭐

权限：学生（只能提交自己的验证，否则 `403`；不存在 `404`；已 `passed` 的再提交返回 `400`）。

请求：`{ "steps": ["6x+2=44", "6x=44-2", "6x=42", "x=7"] }` —— `steps` 规则同 3.3（1~20 步、每步 ≤500 字符，不用传题干之外的说明文字）。

判定口径：与 3.3 诊断管线一致——从题干基准起逐步校验等价性，首个不等价步用同一套规则分类给出错因与解析；`无法解析` 的步骤记问题但不中断。全程无误且最后一步与参考答案等价 → 通过。

响应 `200`：

```json
{
  "id": 1,
  "knowledge_point": "一元一次方程",
  "status": "passed",
  "attempts": 1,
  "passed": true,
  "first_error_seq": null,
  "error_type": null,
  "detail": "全部步骤正确，这道同类题做对了！",
  "steps": [
    {"seq": 1, "text": "6x+2=44", "status": "ok"},
    {"seq": 2, "text": "6x=44-2", "status": "ok"},
    {"seq": 3, "text": "6x=42", "status": "ok"},
    {"seq": 4, "text": "x=7", "status": "ok"}
  ]
}
```

- 通过：`status=passed`、`completed_at` 落库，该知识点在 3.13 中随即变 `fixed`。
- 失败：`status=failed`、`attempts+1`，`first_error_seq` / `error_type` / `detail` 指向首个出错步与解析（最后一步未化简到最终结果时 `error_type` 为 `null`、`detail` 给出提示）；可对同一条记录再次 POST 本接口重做本题，或重新调 3.19 换一道新题。

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

- v0.3.0 起：纠错成功后会给被纠错的学生生成一条站内提醒（见 3.17），文案形如「{教师名}调整了你《{作业标题}》的批改结果：错因由{旧错因}改为{新错因}…」，`related_submission_id` 指向该错题所在的提交。

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

### 4.9 POST /api/teacher/photo-recognize —— 拍照识别题目（v0.2.1 新增）

权限：教师。与 3.11 同一转写能力，服务于「发布作业」表单：上传题目照片 → 识别 → 前端把 `question_text` 填入题干输入框、`steps` 填入标准步骤，教师检查修改后再发布（不直接落库）。

请求：`multipart/form-data`，字段 `file`（jpg / png / webp，≤10MB），图片存同一 `UPLOAD_DIR`。

响应 `200`：结构同 3.11（`image_id` / `image_url` / `question_text` / `steps`），前端实际使用 `question_text` 与 `steps`。

- 注意：v1 直接复用 `transcribe_image`（其 prompt 按学生作答转写调校），未针对题目照片单独调 prompt，识别质量以实际为准。
- 错误：`400`（格式不支持 / 内容为空 / 超过 10MB）；`403`（学生调用）。

### 4.10 DELETE /api/teacher/assignments/{assignment_id} —— 删除已发布作业（v0.3.0 新增）

权限：教师，且**只能删自己发布的作业**（`created_by` 为本人）；非本人发布或不存在统一返回 `404`。

响应 `200`：`{ "deleted": true }`。

- **级联删除**（同一事务内按外键依赖顺序）：该作业的题目（questions）→ 学生提交（submissions）及其步骤（steps）、错题（errors）、订正（corrections）→ 关联到这些提交的提醒（notifications）→ 作文提交（essays，如有）。删除后学生端作业列表、学习报告与班级统计中都不再出现该作业的任何数据。
- 错误：`403`（学生调用）；`404`（作业不存在或非本人发布）。

### 4.11 GET /api/teacher/stats/repair-rate —— 班级知识修复率（v0.4.0 新增）

权限：教师。只读聚合，口径与学生学习报告（3.13）四态完全一致：某个（学生 × 知识点）组合「已修复」= 该生该知识点的错题全部订正且通过了二次验证。

响应 `200`：

```json
{
  "class_repair_rate": 0.5,
  "students_with_errors": 2,
  "total_knowledge_point_pairs": 2,
  "fixed_knowledge_point_pairs": 1,
  "knowledge_points": [
    {"knowledge_point": "一元一次方程", "students_errored": 1, "students_fixed": 1, "repair_rate": 1.0},
    {"knowledge_point": "去括号", "students_errored": 1, "students_fixed": 0, "repair_rate": 0.0}
  ]
}
```

- `class_repair_rate`：全班知识修复率 = 已修复的（学生 × 知识点）组合数 / 出过错的组合数（无任何错题时为 0.0）。
- `knowledge_points[].repair_rate`：该知识点已修复学生数 / 出过错学生数；数组按修复率升序（最需要教学干预的知识点在前）。

---

## 5. /api/health —— 健康检查

### 5.1 GET /api/health

权限：无需登录。

响应 `200`：

```json
{
  "status": "ok",
  "version": "0.4.0",
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
| 报告知识点 `status` | `pending`（待修复）/ `stubborn`（反复出错）/ `awaiting_verify`（已订正待验证，v0.4.0 新增）/ `fixed`（已修复） |
| `verification.status` | `pending` / `passed` / `failed` |

## 7. 变更记录

| 版本 | 日期 | 说明 |
|---|---|---|
| v0.1.0 | 2026-10-06 | 初版冻结 |
| v0.2.0 | 2026-10-07 | 新增 3.11 拍照转写、3.12 首页简报、4.7 发布作业、4.8 教师作业列表；无 breaking 变更 |
| v0.2.1 | 2026-10-07 | 新增 3.13 学习报告、3.14 知识点错题时间线、4.9 教师拍照识别题目；3.12 简报新增 `weak_point_details` 字段（非 breaking）。产品侧变更（无接口 breaking）：作答方式以拍照上传为主，学生端线上文本输入作答入口下线（3.3 接口保留，转写确认后仍走它）；英语作文相关前端入口与文案全部下线（3.6–3.8 接口保留，后续可能恢复）；seed 演示数据改为数学-only（作业更名「第一周数学作业」、去作文题）——仅影响新建数据库，线上已有数据库不受影响；学生/教师作业列表 `created_at` 字段确认为作业日历数据源（双端均有，无变更） |
| v0.3.0 | 2026-10-07 | 新增 3.15 Agent 对话、3.16 对话历史、3.17 提醒列表、3.18 提醒标已读、4.10 删除已发布作业（级联删除，见 4.10）；4.2 教师纠错成功后新增给学生生成提醒的行为。新增表 `chat_messages`、`notifications`（仅新增表，不改现有表结构）。产品侧变更：学生主页对话升级为 LangGraph 交互 Agent（自由聊天问数学 + 工具查本人数据），拍照批改确定性管线不变；学生端批改结果署名统一为「老师批改/批改结果」；作业日历从作业列表页迁至全局右侧栏（通知区 + 日历），学习报告落地层改为四科悬挂卡（数学真实下钻，英语/物理/化学为占位）；交作业页拍照批改改为原地展开，不再跳对话页 |
| v0.3.1 | 2026-10-07 | 无接口变化。产品侧变更：右侧栏按页面分工——学生主页等普通页只放便利贴提醒、学生/教师作业列表页只放日历（点选日期经前端 store 状态筛选本页作业列表，学生页显示当天完成进度条，均带「返回查看全部作业」清除筛选），教师其他页面不挂右栏；收起态悬浮按钮图标随场景变（提醒=邮件+未读角标、日历=日历图标无角标） |
| v0.4.0 | 2026-10-07 | 闭环补完：新增 3.19 创建二次验证（变式题：参数模板 sympy 验算 + Provider 兜底练习模式）、3.20 验证列表、3.21 提交验证作答、4.11 班级知识修复率；3.3/3.5 诊断响应新增 `follow_up_question`（追问，无错为 null）；3.9 订正响应新增 `can_verify`、`knowledge_point`（只加字段）。**口径变更（语义收紧，非字段 breaking）**：3.13 知识点状态升级四态（新增 `awaiting_verify`），「全订正即 fixed」废弃，`fixed` 专指通过二次验证，`fixed_ratio` 定义随之为知识修复率＝通过验证的知识点 / 出过错知识点。新增表 `verifications`（仅新增表，不改现有表结构）。产品侧变更：前端排版整体重做（教师总览 KPI + 双列网格、学习报告双列 + 内嵌验证面板、学生卡片网格、登录左右分栏、品牌动态 Logo 与导航图标动效） |
