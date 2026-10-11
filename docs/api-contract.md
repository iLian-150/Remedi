# Remedi MVP 接口契约（API Contract）

> 版本：v0.13.13（2026-10-12）
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
- v0.5.0 新增字段（只加字段）：`mode`（`online | offline`，无扩展记录时为 `online`）、`workbook_title`（线下作业关联的练习册名，未关联时为 `null`）、`page_range`（如「第12-14页 第1-8题」，可空）、`deadline`（截止时间 ISO 8601，可空）。3.2 作业详情同样包含这四个字段；3.12 简报的 `pending_assignments[]` 亦同步包含。

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
- **教师审核可见性（v0.9.0 新增、v0.13.13 收紧）**：经实时批改入口（3.3 / 3.31 / photo-diagnose）产生的新提交中，只要有任一错因 `confidence < 0.60`，整份提交进入教师审核队列（新表 `submission_reviews`，`status=pending`）；恰好 `0.60` 不进入审核，全对提交也不进入。**待审核期间**，学生侧一切入口都看不到诊断结论：
  - 3.3 / 3.5 / 拍照批改的诊断响应返回占位：`status = "pending_review"`、`review_status = "pending"`、`steps = []`、`errors = []`、`first_error_seq = null`、`follow_up_question = null`；通过后同一响应返回完整诊断且 `review_status = "approved"`。诊断响应另在所有情况下带 `review_status` 字段（只加字段）。
  - 3.4 提交记录每项带 `review_status`；`pending` 时 `error_count` 固定为 `0`（不泄露诊断结论）。
  - 错题本（3.27）不出现待审核提交产生的错题（学生自助收录的 captures 不受影响）；3.9 订正、3.19 创建验证指向待审核错题时返回 `400`。
  - 简报（3.12）、学习报告（3.13 / 3.14）、学习画像（3.10 学生自查）与学生 Agent 工具（get_my_briefing / get_my_report / get_knowledge_point_errors）统计一律滤掉待审核提交（简报的「未完成作业」按已提交口径算，交过的不再重复出现）；教师端（含 4.6 教师查画像、教师 Agent）不受影响，全量可见。
  - **无审核行的历史/种子提交一律视为 `approved`**，演示数据不受审核流影响。通过动作见 4.23~4.26；通过后学生收到 `type = "review_approved"` 的提醒。

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
- `suggestion`：v0.9.1 起改为后端本地模板生成（依据已订正成果、最弱知识点拼装具体建议），不再调用 LLM Provider——画像是高频读接口，避免同步等大模型造成数秒级延迟。响应结构不变。教师端 4.6 查同一画像共用同一实现。

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
- 转写由 Cloudflare Workers AI 视觉模型完成，默认 `@cf/qwen/qwen3.8-27b`（可用 `CLOUDFLARE_VISION_MODEL` 覆盖）；未配置凭证或识别失败时明确返回错误，不使用 Mock 罐头转写。
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

### 3.15 POST /api/student/agent/chat —— 旧接口停用

为保证问答统一使用 Cloudflare Workers AI 并逐字流式呈现，旧 JSON 接口返回 `410 Gone`。请调用 3.15.1 的 SSE 接口；该接口失败时明确发送错误，不返回 Mock/规则拼接回复。模型等待上限为 120 秒。

### 3.15.1 POST /api/student/agent/chat/stream —— 学习助手流式对话

权限：学生。请求 `{ "message": "我哪个知识点最需要加固？", "session_id": 3 }`；`message` 必填且最长 2000 字，`session_id` 选填。另可传 `persist_user_message`（默认 `true`）；用户消息会在开始生成前写入会话，避免刷新或中断时丢失提问。响应为 `text/event-stream`，通过 SSE 事件发送 Cloudflare 模型的流式回复；前端将每个文本块按 Unicode 字符逐字呈现。复用已保存的拍照消息时可传 `false`，避免重复保存内部提示词。模型调用失败会发 `error` 事件，不返回模拟内容。

```text
event: token
data: {"text":"先把方程两边……"}

event: done
data: {"reply":"先把方程两边……", "suggestions":["为什么要移项？"], "session_id":3, "related_mistake":null}
```

- `token`：回复文本块；同一回复可能有多个事件。
- `done`：完整回复、建议追问、会话 id，以及选填的 `related_mistake`（同学科、同知识点最近一条已审核且未归档的历史错题；无匹配时为 `null`）。服务端在生成完成后将助手回复写入会话，并持久化该消息与错题的关联；用户提问已在流开始前保存。
- `error`：流生成中断时发送 `{ "detail": "回复生成中断，请稍后重试。" }`；已经保存的用户提问仍可在历史会话中找回。
- 学生只发题目时，Agent 查询历史同类错题但不创建批改记录；学生明确给出自己的数学作答步骤并要求检查时，Agent 调用 `diagnose_student_text_work` 接入现有数学诊断、错题本和订正流程。全对不创建错题；低置信错因按 3.3 口径进入教师审核。

### 3.16 GET /api/student/agent/history —— 我的对话历史（v0.3.0 新增）

权限：学生。返回最近 50 条对话，时间正序（旧 → 新），供主页对话页回放。

- v0.6.0 起语义收窄：返回的是「当前会话」（最近更新的那条会话）最近 50 条消息；全部会话的列表与单条会话全量消息见 3.23 / 3.25。无任何会话时返回空数组。

响应 `200`：

```json
[
  {"role": "user", "content": "移项为什么要变号", "created_at": "2026-10-07T10:00:00"},
  {"role": "assistant", "content": "方程其实就是一架天平……", "created_at": "2026-10-07T10:00:05"}
]
```

- `role` 枚举：`user` | `assistant`。助手消息可额外带 `related_mistake`；结构见 3.33。

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

### 3.22 POST /api/student/agent/new-session —— 开始新对话（v0.5.0 新增，v0.6.0 语义变更）

权限：学生。**v0.6.0 语义变更**：不再删除任何记录——改为新建一条会话（同 3.24）并将其设为当前会话，旧会话保留在历史列表（3.23）里可找回、可单独删除（3.26）。取代 v0.5.0 的物理删除口径。

请求：无请求体。

响应 `200`：新建的会话对象（结构同 3.23 的列表元素，`message_count` 为 0）。

### 3.23 GET /api/student/agent/sessions —— 我的对话会话列表（v0.6.0 新增）

权限：学生。历史对话面板的数据源：本人的全部会话，按 `updated_at` 倒序（最近聊过的在前）。

响应 `200`：

```json
[
  { "id": 3, "title": "移项为什么要变号", "created_at": "2026-10-07T10:00:00", "updated_at": "2026-10-07T10:05:00", "message_count": 6 },
  { "id": 1, "title": "之前的对话", "created_at": "2026-10-06T09:00:00", "updated_at": "2026-10-06T09:30:00", "message_count": 12 }
]
```

- **旧数据迁移**：首次访问任一会话接口（3.15 / 3.16 / 3.22~3.26）时，若该用户在旧表 `chat_messages` 里还有记录且尚无任何会话，后端自动生成一条标题为「之前的对话」的会话，把旧消息按原顺序完整复制进新表 `chat_session_messages`，随后删掉该用户在旧表的行（防重复迁移）。学生与教师按 `user_id` 各自独立迁移；迁移后 `chat_messages` 不再写入。

### 3.24 POST /api/student/agent/sessions —— 新建对话会话（v0.6.0 新增）

权限：学生。新建一条空会话并成为当前会话。标题先给「新对话」，该会话第一条用户消息到达时自动把标题改为该消息前 20 字。

请求：无请求体。响应 `200`：会话对象（`message_count` 为 0）。

### 3.25 GET /api/student/agent/sessions/{session_id}/messages —— 某会话的全部消息（v0.6.0 新增）

权限：学生。返回该会话的**全部**消息（不截断），时间正序，元素结构同 3.16。会话不存在或不是本人的统一 `404`。

### 3.26 DELETE /api/student/agent/sessions/{session_id} —— 删除一条会话（v0.6.0 新增）

权限：学生。删除本人的一条会话及其全部消息（不可恢复）。会话不存在或不是本人的统一 `404`。

响应 `200`：`{ "deleted": true }`。

### 3.27 GET /api/student/mistakes —— 我的错题本（v0.7.0 新增）

权限：学生。仅返回当前登录学生自己的错题；默认 `archived=false` 返回当前错题，`archived=true` 返回已移出错题本的记录。每条错题独立保存移出状态，整份作业移出只是一次批量更新。按作业与错误类别整理所需的数据一次性返回，不分页。

响应 `200`：

```json
[
  {
    "id": 12,
    "submission_id": 8,
    "question_id": 3,
    "assignment_id": 2,
    "assignment_title": "第一周数学作业",
    "assignment_created_at": "2026-10-07T10:30:00",
    "question_subject": "math",
    "question_order": 2,
    "question_stem": "解方程：2x+3=7",
    "correct_answer": "x=2",
    "knowledge_point": "一元一次方程",
    "error_type": "计算失误",
    "is_stubborn": false,
    "detail": "移项后符号计算错误。",
    "step_seq": 2,
    "step_text": "2x=7+3",
    "created_at": "2026-10-07T10:35:00",
    "submitted_at": "2026-10-07T10:35:00",
    "category_key": "math:calculation",
    "category_label": "计算与运算",
    "category_studied": false,
    "archived_at": null,
    "similar_occurrences": [],
    "latest_correction": null,
    "verification_status": null
  }
]
```

- `category_studied` 是当前学生对该作业、该错误类别的学习标记；`archived_at` 非空表示这条错题已移出当前错题本。
- `similar_occurrences` 只包含该学生在更早作业中同类别的错题；`latest_correction` 与 `verification_status` 是这条错题最近一次订正和二次验证状态，没有记录时为 `null`。
- `submitted_at`（v0.9.0 新增，只加字段）：错题所属提交的提交时间（订正页日历按此打点）；自主收录条目无提交，取收录时间兜底。
- `correct_answer`：该错题题目的参考答案，仅在本人提交后的错题复习接口中返回；数学一元方程优先从题干推导完整解集，其他数学答案仅在机械验算通过后返回；无法核验时为 `null`。自主收录条目为 `null`。
- 列表也包含学生主动收录的题目，`source_kind="student_saved"`，带有 `capture_id` 与 `image_url`；这类条目不属于诊断错误，不计入学习报告或教师错误统计。
- 错误类别分类规则与 Learning-Diagnosis-System 一致：结合学科、错因和知识点关键词归类；通用诊断类型优先按知识点归类，未命中规则时用规范化后的错因文本作为稳定类别键。

### 3.28 PATCH /api/student/mistakes/categories —— 更新错因学习状态（v0.7.0 新增）

权限：学生。只能更新本人在指定作业中实际出现的错误类别；已整体移出的作业不可更新。

请求：`{ "assignment_id": 2, "category_key": "math:calculation", "studied": true }`。`studied=false` 会撤销标记。

响应 `200`：`{ "assignment_id": 2, "category_key": "math:calculation", "studied": true }`。作业或类别不存在、或已归档时返回 `404`。

### 3.29 PATCH /api/student/mistakes/assignments/{assignment_id}/archive —— 批量移出或恢复错题（v0.7.0 新增）

权限：学生，只能整理本人有错题的作业。请求 `{ "archived": true }` 时，对该作业当前仍在错题本中的记录按类别检查，必须先标记全部类别已学习，否则返回 `409`；通过后只归档当前活跃记录。恢复时传入 `occurrence_ids`，仅恢复列表中的、属于本人和该作业的已归档记录。此操作只改变错题本展示状态，不删除提交、诊断、订正或验证记录。

归档请求：`{ "archived": true }`。恢复请求：`{ "archived": false, "occurrence_ids": [12, 13] }`。

响应 `200`：`{ "assignment_id": 2, "archived_ids": [12], "archived_at": "2026-10-07T11:00:00" }`。恢复响应返回实际恢复的 ID 列表；空列表不执行恢复。不存在或本人没有该作业错题时返回 `404`。

### 3.30 PATCH /api/student/mistakes/{error_id}/archive —— 移出或恢复单条错题（v0.7.0 新增）

权限：学生，只能操作本人错题。请求 `{ "archived": true }` 移出单条记录，`false` 恢复该记录；不要求先学完其错误类别。

响应 `200`：`{ "id": 12, "student_id": 2, "archived_at": "2026-10-07T11:00:00" }`；恢复时 `archived_at` 为 `null`。记录不存在或不属于本人时返回 `404`。重复设置相同状态是幂等的。

新增表 `student_mistake_category_reviews` 保存学习标记，`student_mistake_archives` 按学生和错题 ID 保存移出时间，`student_mistake_events` 记录单条/整份作业归档与恢复事件；只新增表，不改现有表结构。教师删除作业时会清理相应状态与事件。

### 3.31 POST /api/student/photo-review —— 按图片作答情况答疑或诊断

权限：学生。请求为 `multipart/form-data`，必填 `file`（jpg / png / webp，≤10MB），可选 `question_id`（学生已选定的作业数学题）。学习助手可额外传 `save_to_chat=true`、`chat_session_id` 和 `chat_prompt`；服务端会在开始识别前保存照片提问，并在识别结束或失败后保存文字结果。返回 `session_id` 供前端继续写入同一会话。照片原图仍按既有流程处理，不作为聊天历史附件恢复。

无学生作答证据时返回 `mode="answer"`、识别题干和 `capture_id`；前端将题干交给学习助手解答，但此时不创建 `Submission` / `Error`，也不展示为错题。学生点「加入错题本」或在同一对话里明确要求收录后，调用 3.32。

检测到学生作答时，若传入 `question_id`，直接复用 3.3 数学诊断；自由上传则创建只归属该学生的题目记录并诊断。确有错误时自动写入错题/订正数据；任一错因置信率低于 60% 时整份提交进入教师审核，审核通过后对学生显示，全对时不创建错题。视觉识别置信率低于 0.45 或有作答但无法辨认步骤时返回 `422`，不产生诊断记录。

响应 `200`：`{"mode":"answer|diagnosis","question_text":"…","steps":[],"capture_id":1,"diagnosis":null}`。`mode=diagnosis` 时 `diagnosis` 为 3.3 响应体，`capture_id` 为 `null`。

### 3.32 POST /api/student/photo-captures/{capture_id}/save —— 主动收录题目

权限：学生，只能收录本人上传的暂存题目。请求 JSON：`{"explanation":"学习助手给出的讲解"}`。重复请求幂等；成功后题目出现在 3.27 错题本，原图通过返回条目的 `image_url` 查看。

新增表 `student_question_captures` 保存待收录图片和主动收录状态；仅新增表，不修改原诊断与错误记录表。学生自主上传并自动诊断的内部作业容器不会出现在学生作业列表中。

### 3.33 GET /api/student/questions/{question_id}/related-mistake —— 查看历史同类错题

权限：学生。按当前题目的学科与知识点查找该学生最近一条已审核、未归档的历史错题；不匹配当前作业，避免把本次题目作为历史记录。没有匹配时返回 `null`。该接口只返回当前学生自己的记录。

响应 `200`：

```json
{
  "id": 21, "submission_id": 8, "question_id": 4, "assignment_id": 2,
  "assignment_title": "第一周数学作业", "assignment_created_at": "2026-10-01T10:00:00",
  "question_subject": "math", "question_stem": "解方程：2x+3=7",
  "solution_steps": ["两边同时减去 3：2x = 7 - 3", "化简：2x = 4", "两边同时除以 2：x = 2", "验算：代入 x=2 后，左边=7、右边=7，等式成立。"],
  "knowledge_point": "一元一次方程", "error_type": "概念混淆",
  "detail": "移项时没有改变符号", "step_seq": 2, "step_text": "2x=7+3",
  "created_at": "2026-10-02T10:00:00", "latest_correction": null
}
```

`solution_steps` 仅对系统能安全推导的数学题返回步骤，不返回教师存储的标准答案；其他题型返回空数组。匹配按知识点名精确判断（忽略空格与大小写）。

### 3.34 POST /api/student/question-captures —— 主动收录文本题目

权限：学生。学习助手中的文本题目被学生明确要求加入错题本时调用。请求 JSON：`{"question_text":"解方程：2x+3=7","subject":"math","explanation":"可选的讲解"}`；`question_text` 必填，`subject` 默认 `math`。成功后记录立即出现在 3.27 错题本，`image_url` 为 `null`。

### 3.35 Agent 历史消息的同类错题字段

3.16 与 3.25 的助手消息新增选填 `related_mistake`，用于会话恢复后继续显示「回看以前错过的同类题」入口；结构同 3.33 响应。字段为 `null` 时不显示入口。

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
- v0.5.0 新增选填字段（不传 = 线上作业）：`mode`（`online | offline`，默认 `online`）、`workbook_id`、`page_range`、`deadline`（ISO 8601）。`mode=offline` 时把这四项写入新表 `assignment_ext`（题目仍走原 `questions` 结构，由教师拍照识别题目页产生）；`workbook_id` 必须指向本人经 4.15 上传的练习册，否则 `400`。响应同步新增 `mode` / `workbook_title` / `page_range` / `deadline` 四个字段。

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

### 4.12 POST /api/teacher/agent/chat —— 旧接口停用

为保证问答统一使用 Cloudflare Workers AI 并逐字流式呈现，旧 JSON 接口返回 `410 Gone`。请调用 4.12.1 的 SSE 接口；该接口失败时明确发送错误，不返回 Mock/规则拼接回复。模型等待上限为 120 秒。

### 4.12.1 POST /api/teacher/agent/chat/stream —— 班级数据助理流式对话

权限：教师。请求 `{ "message": "《第一周数学作业》谁还没交？", "session_id": 2 }`；`message` 必填且最长 2000 字，`session_id` 选填。响应为 `text/event-stream`：`token` 事件携带模型文本块，`done` 事件携带完整回复、建议追问与会话 id；模型错误时发送 `error` 事件，不生成模拟回复。教师端前端逐 Unicode 字符呈现文本，并在成功后保存助手回复。学生调用返回 `403`。

### 4.13 GET /api/teacher/agent/history —— 教师对话历史（v0.5.0 新增）

权限：教师。响应 `200`：最近 50 条（时间正序），元素结构同 3.16（`role` / `content` / `created_at`）。v0.6.0 起同 3.16，只返回当前会话的消息。

### 4.14 POST /api/teacher/agent/new-session —— 开始新对话（v0.5.0 新增，v0.6.0 语义变更）

权限：教师。**v0.6.0 语义变更**同 3.22：新建一条会话并设为当前（同 4.20），不再删除任何记录。请求无请求体。

响应 `200`：新建的会话对象。

### 4.15 POST /api/teacher/workbooks —— 上传练习册 PDF（v0.5.0 新增）

权限：教师。把整本练习册 PDF 存入练习册知识库（新表 `workbooks`），发布线下作业（4.7 `mode=offline`）时可直接选用。

请求：`multipart/form-data`，字段 `file`（仅 PDF，≤30MB）。文件存 `UPLOAD_DIR/workbooks/`，标题默认取文件名（去扩展名）。

响应 `200`：

```json
{
  "id": 1,
  "title": "数学练习册",
  "file_url": "/api/uploads/workbooks/20261007120000_ab12cd34.pdf",
  "cover_url": "/api/uploads/covers/1.jpg",
  "created_at": "2026-10-07T12:00:00"
}
```

- `cover_url`（v0.6.0 新增）：上传成功后后端尝试把 PDF 第一页渲染成封面图（PyMuPDF，约 150dpi），存 `UPLOAD_DIR/covers/{id}.jpg` 并经 `/api/uploads/covers/{id}.jpg` 访问；渲染失败（PDF 损坏等）静默跳过，`cover_url` 为 `null`，前端用纯色书脊兜底。封面按文件名约定关联，不给 `workbooks` 表加列。
- 错误：`400`（非 PDF / 内容为空 / 超过 30MB）；`403`（学生调用）。

### 4.16 GET /api/teacher/workbooks —— 我的练习册知识库（v0.5.0 新增）

权限：教师（只查本人上传的）。响应 `200`：`{ "total": n, "items": [...] }`，item 结构同 4.15 响应，按上传时间倒序。v0.6.0 起列表时若某本书 PDF 在盘上但封面缺失，会懒生成一次再返回 `cover_url`。

### 4.17 DELETE /api/teacher/workbooks/{workbook_id} —— 删除练习册（v0.5.0 新增）

权限：教师，且**只能删自己上传的**；非本人或不存在统一返回 `404`。连同磁盘上的 PDF 文件一并删除；已被线下作业引用的也可删除，对应 `assignment_ext.workbook_id` 自动置空（作业与页码等其余信息保留）。

响应 `200`：`{ "deleted": true }`。

### 4.18 POST /api/teacher/assignments/{assignment_id}/remind —— 一键提醒未交学生（v0.5.0 新增）

权限：教师，且**只能提醒自己发布的作业**；非本人发布或不存在统一返回 `404`。

行为：找出「还没提交该作业全部题目」的学生（口径与 3.12 简报的完成判定一致：每道题都有 Submission 或 Essay 记录才算完成），给每人写一条站内提醒（复用 `notifications` 表，`type=teacher_reminder`，`related_submission_id` 为 `null`），文案为「{教师名}提醒你：《{作业标题}》还没有完成，记得及时提交哦」，学生在主页便利贴提醒区收到。已全部完成的学生不会收到。

请求：无请求体。响应 `200`：`{ "reminded_count": 2 }`（本次实际写入提醒的学生数）。

### 4.19 GET /api/teacher/agent/sessions —— 教师对话会话列表（v0.6.0 新增）

权限：教师。语义与字段同学生端 3.23（含旧 `chat_messages` 数据的自动迁移，按 `user_id` 独立进行）。

### 4.20 POST /api/teacher/agent/sessions —— 新建教师对话会话（v0.6.0 新增）

权限：教师。语义同学生端 3.24（标题先给「新对话」，首条用户消息到达时自动改为该消息前 20 字）。

### 4.21 GET /api/teacher/agent/sessions/{session_id}/messages —— 某会话的全部消息（v0.6.0 新增）

权限：教师。语义同学生端 3.25（全部消息正序；不存在/非本人 `404`）。

### 4.22 DELETE /api/teacher/agent/sessions/{session_id} —— 删除一条教师会话（v0.6.0 新增）

权限：教师。语义同学生端 3.26（连同消息一并删除；不存在/非本人 `404`）。响应 `200`：`{ "deleted": true }`。

### 4.23 GET /api/teacher/reviews/pending —— 待审核队列（v0.9.0 新增）

权限：教师。AI 批改完还在等老师审核的提交，按提交时间正序（先交先审）。导航「待审核」角标与待审核页共用本接口。

响应 `200`：`{ "count": 待审总数, "items": [...] }`，每项：

```json
{
  "submission_id": 12,
  "student": { "id": 2, "name": "林小夏", "student_no": "S2026001", "role": "student", "created_at": "…" },
  "assignment_id": 1,
  "assignment_title": "第一周数学作业",
  "question_id": 1,
  "question_stem": "解方程：2x+3=7",
  "subject": "math",
  "knowledge_point": "一元一次方程",
  "error_count": 1,
  "submitted_at": "2026-10-08T01:00:00"
}
```

### 4.24 GET /api/teacher/reviews/{submission_id} —— 审核详情（v0.9.0 新增）

权限：教师。一份提交的完整 AI 分步诊断（教师端全量可见，不受学生侧可见性口径影响）+ 审核状态。不存在 `404`。

响应 `200`：`{ submission_id, student(UserOut), assignment_title, question(QuestionOut), submitted_at, review_status("pending"|"approved"), diagnosis(同 3.5 DiagnosisOut，另带 review_status) }`。

### 4.25 POST /api/teacher/reviews/{submission_id}/approve —— 审核通过（v0.9.0 新增）

权限：教师。把该提交置为 `approved` 并给学生写一条提醒（`notifications.type = "review_approved"`，`related_submission_id` 指向该提交，文案口径为「老师已审核通过……去看看诊断吧」）。幂等：已通过的重复调用不重复发提醒。不存在 `404`。

「改后通过」不设单独接口：审核详情里先调 4.2 一键纠错改错因（待审核期间纠错**不**发 `teacher_correction` 提醒，避免向学生泄露未放行的诊断），再调本接口即可。

响应 `200`：`{ "submission_id": 12, "review_status": "approved" }`。

### 4.26 POST /api/teacher/reviews/approve-all —— 全部通过（v0.9.0 新增）

权限：教师。把当前队列全部 pending 提交置为 `approved`，逐个给学生发 `review_approved` 提醒。

响应 `200`：`{ "approved_count": 本次通过条数 }`。

---

## 5. /api/health —— 健康检查

### 5.1 GET /api/health

权限：无需登录。

响应 `200`：

```json
{
  "status": "ok",
  "version": "0.7.0",
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
| 作业 `mode`（v0.5.0 新增） | `online`（线上作业）/ `offline`（线下练习册作业） |
| 提醒 `type` | `teacher_correction`（教师纠错）/ `teacher_reminder`（教师提醒未交，v0.5.0 新增）/ `review_approved`（审核通过，v0.9.0 新增） |
| 审核 `review_status`（v0.9.0 新增） | `pending`（待教师审核，学生不可见诊断）/ `approved`（已通过；无审核行的历史/种子提交按此口径）；学生侧诊断响应 `status` 在 pending 时为 `pending_review` |

## 7. 变更记录

| 版本 | 日期 | 说明 |
|---|---|---|
| v0.1.0 | 2026-10-06 | 初版冻结 |
| v0.2.0 | 2026-10-07 | 新增 3.11 拍照转写、3.12 首页简报、4.7 发布作业、4.8 教师作业列表；无 breaking 变更 |
| v0.2.1 | 2026-10-07 | 新增 3.13 学习报告、3.14 知识点错题时间线、4.9 教师拍照识别题目；3.12 简报新增 `weak_point_details` 字段（非 breaking）。产品侧变更（无接口 breaking）：作答方式以拍照上传为主，学生端线上文本输入作答入口下线（3.3 接口保留，转写确认后仍走它）；英语作文相关前端入口与文案全部下线（3.6–3.8 接口保留，后续可能恢复）；seed 演示数据改为数学-only（作业更名「第一周数学作业」、去作文题）——仅影响新建数据库，线上已有数据库不受影响；学生/教师作业列表 `created_at` 字段确认为作业日历数据源（双端均有，无变更） |
| v0.3.0 | 2026-10-07 | 新增 3.15 Agent 对话、3.16 对话历史、3.17 提醒列表、3.18 提醒标已读、4.10 删除已发布作业（级联删除，见 4.10）；4.2 教师纠错成功后新增给学生生成提醒的行为。新增表 `chat_messages`、`notifications`（仅新增表，不改现有表结构）。产品侧变更：学生主页对话升级为 LangGraph 交互 Agent（自由聊天问数学 + 工具查本人数据），拍照批改确定性管线不变；学生端批改结果署名统一为「老师批改/批改结果」；作业日历从作业列表页迁至全局右侧栏（通知区 + 日历），学习报告落地层改为四科悬挂卡（数学真实下钻，英语/物理/化学为占位）；交作业页拍照批改改为原地展开，不再跳对话页 |
| v0.3.1 | 2026-10-07 | 无接口变化。产品侧变更：右侧栏按页面分工——学生主页等普通页只放便利贴提醒、学生/教师作业列表页只放日历（点选日期经前端 store 状态筛选本页作业列表，学生页显示当天完成进度条，均带「返回查看全部作业」清除筛选），教师其他页面不挂右栏；收起态悬浮按钮图标随场景变（提醒=邮件+未读角标、日历=日历图标无角标） |
| v0.4.0 | 2026-10-07 | 闭环补完：新增 3.19 创建二次验证（变式题：参数模板 sympy 验算 + Provider 兜底练习模式）、3.20 验证列表、3.21 提交验证作答、4.11 班级知识修复率；3.3/3.5 诊断响应新增 `follow_up_question`（追问，无错为 null）；3.9 订正响应新增 `can_verify`、`knowledge_point`（只加字段）。**口径变更（语义收紧，非字段 breaking）**：3.13 知识点状态升级四态（新增 `awaiting_verify`），「全订正即 fixed」废弃，`fixed` 专指通过二次验证，`fixed_ratio` 定义随之为知识修复率＝通过验证的知识点 / 出过错知识点。新增表 `verifications`（仅新增表，不改现有表结构）。产品侧变更：前端排版整体重做（教师总览 KPI + 双列网格、学习报告双列 + 内嵌验证面板、学生卡片网格、登录左右分栏、品牌动态 Logo 与导航图标动效） |
| v0.5.0 | 2026-10-07 | 教师端 AI 入口 + 发布双模式：新增 4.12 教师 Agent 对话、4.13 教师对话历史、4.14 教师新对话、3.22 学生新对话（双端「新对话」均删除本人在 `chat_messages` 的记录，复用同一张表不加列）；新增练习册知识库 4.15 上传 PDF（≤30MB）、4.16 列表、4.17 删除（连文件删，被引用时 `assignment_ext.workbook_id` 置空）；4.7 发布作业新增选填 `mode` / `workbook_id` / `page_range` / `deadline`，`mode=offline` 写新表 `assignment_ext`；3.1 / 3.2 / 3.12 与教师作业列表/详情响应新增 `mode` / `workbook_title` / `page_range` / `deadline` 字段（只加字段）；新增 4.18 一键提醒未交学生（写 `notifications`，`type=teacher_reminder`）。新增表 `workbooks`、`assignment_ext`（仅新增表，不改现有表结构）。产品侧变更：教师端新增「AI 助手」对话页（快捷提问 chips）；双端对话页右上角加「新对话」按钮（不进左侧导航）；发布页第一步选模式（线上 / 线下·练习册两张大选项卡），线下模式选练习册 + 页码 + 拍照识别题目页成草稿题；学生作业卡/简报/交作业页与教师作业列表展示「线下练习」徽标 + 练习册名 + 页码 + 截止，学生作答方式与线上一致；教师作业列表新增「提醒未交」按钮；学习报告科目吊牌点击播放掉落动画（挂绳断开、卡片加速下坠淡出后展开详情，详情从上方落下带小回弹，`prefers-reduced-motion` 时直接展开） |
| v0.6.0 | 2026-10-07 | 对话会话化 + 教师助手全屏 + 报告拆页 + 拍照一键直达 + 书架：新增 3.23~3.26 / 4.19~4.22 双端会话接口（列表 / 新建 / 某会话消息 / 删除会话）；3.15 / 4.12 chat 请求新增选填 `session_id`、响应新增 `suggestions`（建议追问，规则映射生成，最多 3 条）与 `session_id`（只加字段）；3.16 / 4.13 history 语义收窄为当前会话消息；**口径变更**：3.22 / 4.14「新对话」由物理删除改为新建会话（旧会话保留可找回），旧 `chat_messages` 数据在首次访问会话接口时自动迁移为一条「之前的对话」会话（复制后清旧表行），上下文按会话隔离；新增表 `chat_sessions`、`chat_session_messages`（仅新增表，不改现有表结构，`chat_messages` 迁移后停用）；4.15 / 4.16 练习册响应新增 `cover_url`（PDF 首页封面图，上传时渲染、列表时懒生成，失败为 `null`；新增依赖 PyMuPDF）。产品侧变更：教师 AI 助手改全屏版式并排到教师导航第一位（登录落点不变），双端对话页加「历史对话」面板（Muse 式会话列表：标题+相对时间+消息数+单独删除）与回复后建议气泡；学习报告科目详情拆为独立页 `/student/report/:subject`（点吊牌掉落动画后跳页，带「返回学习报告」按钮，`?verify=` 深链随之改指详情页）；交作业页拍照批改改 direct 模式（选图后自动转写并直接出诊断卡，卡内可展开修改重交），对话页保持确认模式；教师端新增「我的练习」书架页（PDF 自动截第一页作封面陈列，末位虚线「+」添加，点书可查看/发布/删除，发布页练习册选择同步显示封面缩略图并支持书架预选跳入） |
| v0.6.2 | 2026-10-07 | 无接口变化。产品侧变更：双端会话导航按 ChatGPT 网页版式移入左侧栏（新对话按钮 + 按今天/昨天/更早分组的会话列表、当前会话高亮、悬停删除二次确认），会话状态移入双端 store 并与对话页同步；左侧栏可收起，状态存入 localStorage，移动端沿用抽屉；双端聊天输入区改为悬浮毛玻璃卡。 |
| v0.7.0 | 2026-10-07 | 学生导航的「诊断报告」改为完整错题本入口，新增 3.27~3.30 错题列表、错因学习状态、单条移出及按作业批量移出/指定记录恢复接口；分类语义、逐错题归档状态和归档事件沿用 Learning-Diagnosis-System 规则，仅新增表、不改现有表。前端提供卡片笔记、便利贴、思维导图、关联图四种视图，错题可直接进入诊断详情或定位订正；原单次提交诊断页保留为 `/student/diagnosis`。 |
| v0.8.0 | 2026-10-07 | 学习助手照片流程按作答证据分流：无作答先回答，明确收录后才进入错题本；有作答则自动诊断并把识别出的错误写入既有错题管线。新增 3.31 / 3.32 及 `student_question_captures` 表；自由上传的诊断容器隐藏在学生作业列表之外。 |
| v0.8.1 | 2026-10-07 | 无接口变化。合并修复：学生对话页（StudentChat）在错题本合并时退回的旧会话实现已修复——移除弹层式历史面板与页面自持会话状态，改走 v0.6.2 的 store 会话状态层（本页侧栏挂同款 SidebarSessions + watch `sessionView` 同步重渲染，发送后回写当前会话并刷新侧栏列表，与教师端同一套会话行为）；底部输入区恢复悬浮毛玻璃卡。错题本相关功能（消息「加入错题本」、意图识别收录、批改自动收录提示、错题本入口）完整保留。 |
| v0.8.2 | 2026-10-08 | 无接口变化。产品侧统一重做：全局侧栏成为双端唯一侧栏（学生对话页页内侧栏删除，会话区与收起机制双端统一走 App.vue 全局侧栏）；导航图标动效补齐 sparkles/book；右栏未读数改由 student store 持有（进学生页面刷新），展开状态按场景分键存储，提醒/日历 FAB 拆为专属按钮；错题本样式收编为一份作用域样式表并整体换回设计令牌色板，便利贴与右栏统一配色，字符图标全量 SVG 化；路由正名：错题本 canonical 改为 `/student/mistakes`，`/student/feedback` 保留重定向到 `/student/diagnosis`，诊断页组件更名 StudentDiagnosis。 |
| v0.9.0 | 2026-10-08 | **教师审核流**：新增表 `submission_reviews`（仅新增表，不给现有表加列）；新增 4.23 待审核队列、4.24 审核详情、4.25 审核通过、4.26 全部通过。经实时批改入口（3.3 / 3.31 / photo-diagnose）产生的新提交先建 `pending` 审核行，教师通过前学生侧全入口不可见诊断（3.3/3.5 诊断响应返回 `status="pending_review"` 占位、3.4 带 `review_status` 且 pending 时 `error_count=0`、错题本过滤、订正/验证拦截、简报/报告/画像/Agent 工具统计过滤；口径全文见 3.3 下「教师审核可见性」）；无审核行的历史/种子提交视为 `approved`。通过后给学生发 `review_approved` 提醒；4.2 纠错在待审核期间不提前发学生提醒（改后通过 = 4.2 + 4.25 组合）。只加字段：诊断响应与 3.4 新增 `review_status`、4.1 教师错误项新增 `submission_id` / `review_status`、3.27 错题新增 `submitted_at`（订正日历打点）、`UserOut` 新增 `created_at`（档案黑板「加入时间」）。会话列表（3.23 / 4.19）本就返回 `message_count`，前端新建会话动作据此防重复：当前激活会话为空（0 条消息）时点「新对话」不再新建。产品侧变更：左侧栏收起改图标轨（68px 只留图标+悬停气泡，删整条滑出+FAB）；教师导航新增「待审核」带待审数角标，批改列表给 pending 打标并可直达审核详情；学生欢迎屏简报改卡片组（未完成作业/待订正/需加固三卡，整卡可点）；交作业页作业切换改顶部 sticky 独立条、拍照批改全程本题内完成不跳级；订正页新增订正日历按提交日期筛选错题；学生「我的档案」黑板化（木框黑板 + 粉笔字个人信息与掌握度粉笔条 + 奖状墙 + 课表式成长记录表）。 |
| v0.9.1 | 2026-10-08 | 无接口变化。产品侧变更：①订正日历迁入右侧栏——订正页（/student/corrections）右栏切换为「订正日历」模式（收起态 FAB 同走 cal-fab），按错题所属提交日期打点+计数，点选日期经 student store 的 correctionsDateFilter 与订正页共享筛选，页内顶部出筛选状态条（「查看全部」清除）；订正页页内日历（v0.9.0）整段移除；可订正错题的拉取/合并/过滤口径抽到 store.fetchCorrectableMistakes 供页与右栏共用，右栏展开状态新增分键 remedi-rail-open-corrections。②我的档案提速：3.10 学习画像的 suggestion 改为后端本地模板生成（stats._profile_suggestion：先肯定已订正成果，再点名最弱知识点给「订正→变式题验证」的具体动作），画像接口不再同步调用 LLM Provider；4.6 教师查画像共用同一函数同步受益，响应结构不变。排查结论：学生端高频读接口中仅画像有此同步生成调用，简报/报告/作业列表/错题本列表本就无 LLM；批改诊断（classify_error）、作文评分、拍照转写、变式题生成属功能主链，保持不动。 |
| v0.9.2 | 2026-10-08 | 无接口变化（3.3 / 3.31 / photo-diagnose 契约均不变）。**口径纠正：作答方式按作业模式分流**——线上作业（`mode=online`）恢复在线作答入口（v0.2.1 下线的是无差别文本入口，本版按 mode 精确恢复）：交作业页线上题目改为卡内文本编辑器（一行一步、上限 20 步与 3.3 校验一致、草稿按题目存 localStorage、交完清除），提交走 3.3 文本提交接口，**与拍照完全同链：后端先经诊断管线产出步骤诊断与错因落库，再建 `pending` 审核行**，学生侧返回 `pending_review` 占位口径与拍照一致；线下练习册（`mode=offline`）保持拍照批改不变。作业列表卡片按钮按 mode 分文案（在线作答 / 拍照批改）并新增「线上作业」徽标。产品侧变更：拍照批改点按直达图库——PhotoGradeFlow 删除组件内「先展开面板再点一次选图」的中间层（`idle` 选图面板整段移除），父级按钮点击当下经组件暴露的 `openPicker()` 直接打开系统图库/文件选择（`accept="image/*"`，格式/大小校验不变）；取消选择不留空面板，「再拍一张/重新拍照」同理直达；对话页自由拍照批改本就直达，未改动。 |
| v0.9.3 | 2026-10-08 | 新增接口：`POST /api/teacher/questions/check-answer`（参考答案 AI 验算：sympy 代入/求解机械验算优先，判不了走 LLM 复核，异常一律收敛 unknown；仅警告、永不拦截发布）。产品侧变更：①学生对话页简报进入对话态后自动收起为吸顶摘要条（可手动展开）；②教师「我的练习」书架标题移到书本上方；③学生作业列表试卷化（纸面+订书钉+装订线，状态改印章呈现，首次进入盖章动画）。 |
| v0.10.0 | 2026-10-08 | **评分系统**（新表 assignment_scoring/question_weights/submission_scores，不动现有表列）：发布作业带 total_score 与每题 weight_pct（无配置=100 分均分）；批改诊断落库时按「满分×正确步数/总步数」折算 ai_score；审核详情带 score 明细，approve 可传 final_score 改分（超满分 400）；学生侧分数仅 approved 后可见（诊断带成绩单字段）；新增 `GET /api/student/report/scores`（历次作业得分聚合+学科/总体平均得分率）。产品侧变更：订正页改便利贴墙（一题一贴、点击撕下进修正区、已订正盖绿印留墙）；作业列表「返回查看全部作业」移入试卷头；学习报告纯化（变式题/验证入口迁出报告页、改到订正页结果区与待验证知识点卡，科目详情改卷轴展开动画，页内错题时间线移除）；报告页右侧栏新增 timeline 模式承载错题时间线（默认收起、点击展开，报告页不再放信箱）。 |
| v0.11.0 | 2026-10-08 | 新增：①过程可疑识别（services/process_check.py，从落库步骤计算：最终答案正确但链条有错步/仅一步到位/不可解析步过半 → 教师待审核详情带 process_check 提示，学生侧仅把追问换成过程追问、不下发任何判定字段）；②教学建议（services/suggestions.py + `GET /api/teacher/suggestions`：按班级修复率/错误率/顽固聚集/作业得分率模板组装建议卡，教师班级总览页展示，教师 Agent 新增 get_teaching_suggestions 工具）。 |
| v0.11.1 | 2026-10-08 | 无接口变化。部署修复：deploy/nginx.conf 补 `client_max_body_size 30m`（与后端练习册 PDF 30MB 上限对齐）与 `client_body_timeout 300s`——此前 nginx 吃默认 1MB，线上超过 1MB 的上传（练习册 PDF、作业照片）都会在网关被 413 拦下、到不了后端；本地直连后端测试绕过了网关故未暴露。后端各上传口径不变（PDF ≤30MB、照片 ≤10MB，超限仍由后端报明确错误）。 |
| v0.11.2 | 2026-10-08 | 无接口变化（仅字段值形态）。封面缓存根治：services/covers 的 cover_url 给封面地址加 `?v=<封面文件 mtime>` 版本参数——封面文件名按 workbook id 固定，删书重传后 id 复用、地址不变时浏览器会拿缓存旧图串图；版本号随后端文件更新而变，前端取到的地址一变浏览器即重新取图。线上实证背景：整本教材上传后封面生成正确（服务器文件与 PDF 第一页一致），用户端所见旧封面为浏览器缓存。 |
| v0.12.0 | 2026-10-08 | 无接口变化。发布作业页两级化与布局重做（TeacherPublish）：第一级只选发布方式（线上/线下两张大卡，点卡进入），第二级才是发布表单（顶部返回条+当前方式徽标；返回不清空已填内容）；mode 写入 route query，刷新与书架深链（?mode=offline&workbook_id=）直达表单级。表单按实际位置并排：基本信息=标题整行+学科/总分一行；线下范围=页码/截止时间一行；题目卡=题干整行+知识点/分值占比一行+标准步骤/参考答案两列。底部操作条吸底（添加一题+占比合计状态+发布常驻可见）。输入控件在发布页内统一样式（1.5px 描边/10px 圆角/浅底/聚焦光环，补齐全局未覆盖的 number 与 datetime-local）。 |
| v0.13.0 | 2026-10-08 | 新增两个接口：①`POST /api/teacher/workbooks/{id}/extract-questions`（按页提题：入参 {page_range} 自由文本，后端 services/pdf_extract.py 解析页码——只认带「页」的段、题号段只作视觉定位提示、按 PDF 页数夹紧、单次 ≤8 页超限 400；指定页以 200 DPI 渲染成图，逐页调 Provider.extract_questions_from_page 由视觉模型拆题，返回 {pages, questions:[{prompt, knowledge_point, source_page}], warnings}，单页失败记 warning 不拖垮整批。只读不落库）②`POST /api/teacher/questions/guess-knowledge-point`（入参 {prompt} 题干 → {knowledge_point}；Provider.guess_knowledge_point：真实 Provider 走文本模型判断，兜底为关键词启发式，判不出返回空串）。AI 分工口径：渲染与页码解析不用 AI；拆题用视觉模型、猜知识点用文本模型；两处产出都是草稿/建议，教师检查修改后才发布，判分链不受影响。前端：线下表单页码区加「从 PDF 自动识别这些页的题目」按钮（草稿逐道填入题目卡，复用拍照追加落点），题目卡知识点输入旁加「AI 识别」按钮。Mock 模式下拆题返回带「示例草稿」前缀的预置题、猜知识点走启发式，全流程可跑。同版附带错题本 UI 错位修复（无头浏览器实测定位）：①错题行——全局旧样式按旧 DOM 把题目按钮与「查看原题」都钉在 grid 第 2 列同一格重叠（题目点不动、摘要被挤成窄条），StudentMistakeNotebook 作用域样式改回横向 flex（题目占满左侧、查看原题右置、题干/错因摘要两行截断）；②思维导图——居中逻辑此前只处理 network，导图打开停在画布左上角、中心节点被推出右缘，MistakeRelationshipMap 居中函数补 mindmap 分支（按 root 点滚动居中，「回到中心」同步生效）；③学习进度条填充色 primary-50 几乎不可见，改主色实色。 |
| v0.13.1 | 2026-10-08 | 作答与发布大修（无新接口，多个接口加字段/改行为）：①学生做题板（StudentSubmit 线上模式重构）：一次只看一道题，题干放大到 19px，去掉知识点徽章等小字与题型显示；底部导航左「答题卡」（弹层题号格：已完成/待审核/未完成/当前）右下角上一题/下一题；数学符号栏（( ) + − × ÷ = · x² x³ xⁿ √ π）点按插入光标处，符号都过后端解析——mathparse 归一化补 −(U+2212)/√/π，且 √ 经 _sqrt_to_pow 改写为幂形式绕开 evaluate=False 下的 SympifyError。②提交规则与延迟批改（新表 assignment_settings/question_groups/question_group_members，不动旧表列）：默认每题只能提交一次，后端 assert_can_submit 在文本提交与拍照批改两入口拦截（400「这道题已经提交过了，每道题只能提交一次」）；教师发布勾选 allow_revision 后，截止前提交只落 status=deferred 的延迟提交（只存原始步骤、不诊断不建审核行，DiagnosisOut 返回 status/review_status=deferred），学生可反复修改以最后一次为准；截止后由 services/deferral.grade_due 统一批改（启动后每分钟清扫 + 复用原提交行 diagnose_submission(reuse=) 保持 id/时间，随后建待审核行；被覆盖的旧版本标 superseded）。没设截止的允许修改作业不延迟、立即批改且放行覆盖。前端提交后锁定（去掉「再交一次」、线下已提交题不再给拍照按钮），允许修改时页面最底部出现「修改作业」区逐题改（截止后自动消失），状态徽章新增「已提交 · 截止后统一批改」。③大题带小题：发布入参加 groups:[{key, stem}] 与 questions[].group_key、allow_revision；作业详情出参加 groups:[{id, stem, order_num}]、questions[].group_id、allow_revision；小题仍是普通 Question 逐题作答/批改/计分，学生端做题板与线下列表在小题上方展示共享「大题材料」。发布落库修正：AssignmentExt 改为恒建行（此前仅线下建行，线上作业的 deadline 会被静默丢弃）。④教师发布补全与修复：基本信息新增「作业说明」输入（后端字段早已就绪、此前无录入入口，学生端只好显示「暂无说明」——学生端改为没填不显示）与「截止时间」（原仅线下表单有，现两种模式共用，学生端信息卡两种模式都显示截止）；标准解题步骤加同款符号做题板；发布页「选模式后错位」修复——选择级原为 880px 居中窄列、表单级整幅宽，点卡进入时内容横向跳动，两级统一内容列宽；两级切换与卡片入场加淡入上移动画、模式卡悬停上浮。⑤AI 界面「去完成」按模式分流：线上作业跳交作业页做题板并定位到第一道未做题（?q=题目 id），线下才引导拍照（此前一律提示拍照上传，与线上作答不符）。 |
| v0.13.2 | 2026-10-10 | 发布作业表单版式收拢（纯前端，无接口/字段变化）：①基本信息——学科 / 作业总分 / 截止时间并到同一行；截止时间加下限约束（datetime-local 的 min 锁定为打开表单时的当前时间，发布提交时再校验一次，早于当前时间直接拦下报错，手输/粘贴同样生效）。②选填折叠——「作业说明」改为交互按钮：默认只显示一行按钮（已填时带「已填」标记），点开才出现输入框，输入框随文案变长自动长高（上限 242px 后内部滚动）；该按钮与「允许学生在截止前修改」开关并在同一行，开关的说明文字只在勾选后展开，基本信息卡常驻内容明显变少。③题目卡（普通题与大题小题同版式）——知识点 / 分值占比 / 参考答案并到同一行：AI 识别按钮贴在知识点输入右侧（原有位置保留成行）、AI 验算按钮改贴到参考答案输入右侧，验算状态提示（验算中/无误/可能有误）整行显示在该行下方；下面整行留给标准解题步骤（符号栏+输入框+参照系提示）。窄屏下各行自动改单列。本版无 AI 参与（纯布局与校验）。 |
| v0.13.3 | 2026-10-10 | 线下发布选书改版 + 识别后自动分值（纯前端，无接口/字段变化）：①练习册选择——表单里不再常驻下拉与封面条：选书做成一个整行按钮（回显已选书名），与「页码 / 题号范围」输入并在同一行；点按钮打开书架面板（遮罩居中层），封面陈列、点选、上传新 PDF、查看已选 PDF、删除已选都收在面板里，点选/上传成功即关面板。②分值自动分配——拍照追加识别与 PDF 按页提题把草稿题填入题目卡后，自动执行一次均分（distributeEvenly 口径：会发布的题等分、最后一题吃尾差、合计恰好 100%），各题占比输入直接落上数值，教师可再手动调整；单题拍照只改本题内容、题数不变，不触发重排。本版无新增 AI（识别沿用既有视觉链）。 |
| v0.13.4 | 2026-10-10 | 发布页逻辑重组（纯前端，无接口/字段变化）：①时间限制面板——基本信息第三格由系统自带 datetime-local 日期框改为「时间限制」字段：外面只显示友好文案（如「10月15日 周三 22:00 截止」，未设时显示「不设截止，点此设置」，不再露出 yyyy/mm/dd 占位格式）；点开是自制日历面板（月历选日、过去日期置灰、今天描边、选中填充主色 + 时/分下拉 + 今天/明天/三天后/一周后 22:00 快捷 chip + 清除截止；选到已过时刻面板内即时黄字提醒，发布校验照旧兜底拦截）。按新逻辑，「允许学生在截止前修改」开关与「备注（作业说明）」一并收进该面板（备注输入框沿用随文案自动长高；字段上在有备注时带「已填备注」标记，开关说明只在勾选后展开）。deadline 内部仍存 YYYY-MM-DDTHH:mm 字符串，提交/延迟批改口径不变。②标题不移位——发布页页头两级共用同一结构：选完发布方式后「重新选择发布方式 + 模式徽章」只出现在标题右侧同一行（原表单级上方多出一行 topbar 会把整页往下顶），副标题文案两级统一。③「练习册与范围」整卡折叠——默认收起只剩标题行（带已选摘要：书名 · 页码范围 / 还没选练习册），点标题行展开选书与页码；发布校验缺练习册/页码时自动展开该卡；书架深链带 workbook_id 进入时默认展开。填页码后点「从 PDF 自动识别」提题的既有流程不变。本版无 AI 参与（纯布局与自制日历控件）。 |
| v0.13.5 | 2026-10-10 | 作业说明位置回调（纯前端，无接口/字段变化）：按用户要求把「作业说明」从 v0.13.4 的时间限制面板里拎出来，恢复为基本信息卡里的独立折叠按钮（点开才出现输入框、随文案自动长高、已填带「已填」标记，回到 v0.13.2 的形态）；时间限制字段上随之去掉「已填备注」标记，时间面板只保留日历选时与「允许学生修改」开关。 |
| v0.13.6 | 2026-10-10 | 标题位置漂移根治 + 提交规则小字常显（纯前端）：①漂移三因齐修——(a) 全局 CSS 加 `html { scrollbar-gutter: stable }`：内容列是居中定宽（.page max-width 1120 + margin auto），页面长短变化时滚动条出现/消失会让整列横向跳数像素；(b) 路由补 scrollBehavior（换页回顶部、同页 query 变化返回 false 不动滚动）：此前未配，从长页面点进发布页会停在原滚动位置、标题看着像变了位置；注意发布页选模式走 router.replace 改 ?mode=，若无条件回顶部反而会把滚动拽回去，故按 path 是否变化区分；(c) 发布页内选模式/返回时去掉 window.scrollTo(0) 跳变，点卡后页面停在原地（矮窗口预滚后点卡实测：scrollY 与标题视口位置一像素不变）。②时间面板里「提交规则」的说明小字改为一直显示（此前仅勾选后展开，没勾的老师看不到两种规则的区别）。 |
| v0.13.7 | 2026-10-10 | 视觉模型切换 Moondream 3.1（后端）：2026-10-10 线上探针实测坐实原视觉模型 @cf/meta/llama-3.2-11b-vision-instruct 的调用一直在失败、静默降级为 Mock 罐头数据（教师拍照识别/学生拍照批改/PDF 提题三条同链功能线上实际未真跑）。按用户决定换成 Cloudflare 模型目录在架的 @cf/moondream/moondream3.1-9B-A2B（同页另一模型 llava-1.5-7b-hf 为 Beta 老式看图说话模型，不适合结构化转写，未采用）。Moondream 不走 OpenAI 兼容 /chat/completions，而是 Workers AI 任务式接口 POST /ai/run/{model}（入参 task=query + image data URI + question 指令，结果在 result.answer），CloudflareProvider 新增 _vision_text 分流：模型名含 moondream 走任务式接口，其余聊天式视觉模型走原 chat/completions；transcribe_image 与 extract_questions_from_page 共用分流，提示词与降级口径不变。CLOUDFLARE_VISION_MODEL 默认值同步改为 Moondream（服务器 override 若显式设了旧值需一并改掉或删掉该行）。 |
| v0.13.8 | 2026-10-10 | 视觉模型改用 qwen3.8-27b 识图（后端，按用户决定）：v0.13.7 上线后探针复验，Moondream 调用仍被拒、继续静默降级 Mock。经查 Cloudflare 官方模型页确认 @cf/qwen/qwen3.8-27b 本身带 Vision（多模态，与文本聊天同一个模型），且它就是账号上已在正常使用的文本模型（无额外条款/开通问题）。CLOUDFLARE_VISION_MODEL 默认值改为 @cf/qwen/qwen3.8-27b，_vision_text 分流里它走标准 /chat/completions + image_url 通道（v0.13.7 的 Moondream 任务式分流保留，换回 Moondream 只需改配置）。文本模型配置未动。 |
| v0.13.9 | 2026-10-11 | 三处逻辑修正（动手前先同步了队友 zhe-w12 当日推送的 8 个提交——错题思维导图、讲解面板、标准解题过程展示等，再在其基础上改）：①教师发布页题目区改「先选后加」：进表单不再默认摆一道空小题，空态先选「添加小题 / 添加大题」，底部按钮同步改名「添加小题」，单题删除不再受「至少留一题」限制；发布校验改严格完整性——没加任何题目、或任一题目卡没填 / 只填一半（缺题干或知识点）、大题缺题干 / 没有小题 / 小题没填满，一律拦截并指明是哪一题（此前空白卡会被静默跳过、照样能发布）；分值占比条在一道题都没有时隐藏。②学生订正页「题目回顾」补全：原来只显示出错的一步、看不到原题——现在展示原来的题目（有原图时带查看链接）、学生当时的全部作答步骤（按 submission_id 拉提交详情，首错步在原步骤里标红并标「出错在这里」，拉不到详情时降级为只显示出错步骤）、解析、正确答案与标准解题过程。③交作业页「正在交的作业」下拉：后端学生作业列表新增 submitted_count（该学生已提交题数，按题去重，含待批改/待审核），下拉只列还没交完的作业并在选项里标已交进度；正在看的作业若已全部交完，只保留一个禁用项标明「已全部提交」；下拉换自制外观（自绘 chevron、聚焦主色描边、长标题省略号）。本版无 AI 参与。 |
| v0.13.10 | 2026-10-11 | 两处细节修正（前端）：①交作业页「正在交的作业」下拉换成自制面板——v0.13.9 只换了收起时的外观，展开的选项列表仍是操作系统原生样式、改不动（用户截图指出）；现改为按钮 + 浮层面板（与发布页时间面板同一语言：圆角卡片、悬停/选中浅蓝底、当前项带勾、副行小字标题数与已交进度、点面板外或 Esc 收起），v0.13.9 的过滤口径不变（只列没交完的、已交完的当前作业留禁用项）。②错题不再直接给出正确答案（用户口径）：订正页「题目回顾」撤掉 v0.13.9 刚加的「正确答案 / 标准解题过程」两个区块——订正前只看原题、自己的原作答（错步标注）与解析，先自己想；错题本讲解面板（MistakePointAssistant）里的正确答案与解题过程改为默认收起，学生点「查看正确答案与解题过程」才显示，切换错题自动收起。本版无 AI 参与。 |
| v0.13.11 | 2026-10-11 | 发布页三件事：①添加题目空态卡删掉说明行，只留标题与按钮。②红色警示改顶部悬浮 toast（fixed 居中浮层 + alert 图标，watch(error) 计时 5 秒自动消失、连续报错重新计时），不再以块级横幅占位把表单往下推。③新增「拍照识别大题」（本项使用视觉 AI）：后端新增 POST /api/teacher/photo-recognize-group 与 Provider.transcribe_group_image——一张图一次拆出共同题干 stem + 全部小题 sub_questions（照片里有解题过程才带每道小题的 steps，没有留空）；Cloudflare 走 _vision_text 视觉通道、专用大题提示词，失败降级 Mock 罐头大题（一次函数题，与单题罐头明显不同）；ABC 给默认实现（Mock/DeepSeek 共用罐头）。前端入口三处：空态、底部工具栏、大题卡头（卡头入口替换本大题内容，已有内容先 confirm），识别后自动均分并逐小题 AI 猜知识点；同时按用户口径撤掉大题内各小题卡上的「拍照识别题目」按钮——识别入口统一在大题层级（独立小题卡的拍照识别与线下拍照追加、PDF 提题保持不变）。 |
| v0.13.12 | 2026-10-11 | 待审核页重构 + 修掉「改分后无法通过审核」：①Bug 根因——最终分输入框是 type=number，Vue 的 v-model 会把值自动转成数字，approveSelected 里对它调 .trim() 直接抛 TypeError、handler 静默死掉（表现：填了分点「通过审核」毫无反应；留空通过则正常，本地已按截图场景复现并定位）。修复：输入改文本型 + 提交时 String() 归一化，并把根因写进代码注释防复发。②页面按用户口径改三级：一级按作业分卡（学生数/待审份数/有问题与全对计数/最近提交），点进作业后按学生分——左列上方是学生个人信息卡（头像首字、姓名可跳学生画像、学号、本作业待审题数与该生题目列表），下方是本作业学生名单；右列是该生的答题情况（题目与提交时间、过程提示、分步诊断、错因复核、AI 评分），通过后自动定位到同学生下一题 → 下一位学生 → 回作业列表。③最终分换正式的分值编辑器：大号数字输入带「分」后缀与聚焦描边、改分后数字变主色、本题满分参照、快捷钮「用 AI 评分 / 给满分」、说明小字；深链 ?submission_id= 预选改为自动进入对应作业与学生。本版无 AI 参与。 |
| v0.13.13 | 2026-10-12 | 学生作答与历史错题联动：批改后仅将任一错因置信率低于 60% 的提交送教师审核，全对与高置信错题直接反馈；学习助手 LangGraph 查询同学科/知识点历史错题并在回复下显示回看入口；识别文本数学作答后复用诊断/错题/订正流程；作业每题下方复用同一详情弹窗；支持明确收录文本题目。新增 3.33~3.35 与 `chat_session_message_mistake_links` 表。 |
