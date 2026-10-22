# Remedi MVP 数据表设计（Schema Design）

> 版本：v0.1.0（2026-10-06），与 `api-contract.md` 同步冻结。
> 数据库：MVP 用 **SQLite**，但表结构按 **PostgreSQL 兼容**设计——只使用标准列类型（INTEGER / VARCHAR / TEXT / DOUBLE PRECISION / BOOLEAN / TIMESTAMP），JSON 以 TEXT 存序列化字符串，不用任何 SQLite 专有语法/函数。迁移到 PostgreSQL 时只需：TEXT 型 JSON 列 → JSONB、`TIMESTAMP` → `TIMESTAMPTZ`（可选）、自增列改用 IDENTITY。

## 1. 类型映射约定

| 本设计中的类型 | SQLite 实际 | PostgreSQL 目标 |
|---|---|---|
| INTEGER（主键自增） | INTEGER PRIMARY KEY AUTOINCREMENT | INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY |
| VARCHAR(n) | TEXT（SQLAlchemy 映射） | VARCHAR(n) |
| TEXT | TEXT | TEXT |
| DOUBLE PRECISION | REAL | DOUBLE PRECISION |
| BOOLEAN | INTEGER 0/1（SQLAlchemy 自动转换） | BOOLEAN |
| TIMESTAMP | TIMESTAMP（Python 侧 `datetime.now()` 赋值，不用数据库函数） | TIMESTAMPTZ |

**硬性规则**：
- 默认值一律在 Python 侧赋值（如 `default=datetime.now`），不用 `server_default`，避免方言差异。
- JSON 字段存 `json.dumps(...)` 后的 TEXT，PostgreSQL 迁移时改为 JSONB 即可无缝读取。
- 外键只做逻辑关联 + SQLAlchemy `ForeignKey` 声明，不依赖数据库级联行为。

## 2. 表清单

### 2.1 users —— 用户

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| id | INTEGER PK 自增 | 否 | — | 主键 |
| name | VARCHAR(64) | 否 | — | 姓名（登录用用户名） |
| student_no | VARCHAR(32) UNIQUE | 是 | NULL | 学号，全局唯一；教师可为空 |
| role | VARCHAR(16) | 否 | — | `teacher` \| `student` |
| created_at | TIMESTAMP | 否 | now | 创建时间 |

- 索引：`uq_users_student_no`（唯一）、`ix_users_role`。
- 约束说明：`name + role` 组合在 mock 登录时用于查找用户（应用层保证，MVP 不建联合唯一索引）。

### 2.2 assignments —— 作业

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| id | INTEGER PK 自增 | 否 | — | 主键 |
| title | VARCHAR(128) | 否 | — | 作业标题 |
| description | TEXT | 是 | NULL | 作业说明 |
| created_by | INTEGER FK → users.id | 是 | NULL | 出题教师 |
| created_at | TIMESTAMP | 否 | now | 创建时间 |

### 2.3 questions —— 题目

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| id | INTEGER PK 自增 | 否 | — | 主键 |
| assignment_id | INTEGER FK → assignments.id | 否 | — | 所属作业 |
| subject | VARCHAR(16) | 否 | — | `math` \| `english` |
| knowledge_point | VARCHAR(64) | 否 | — | 知识点（如"一元一次方程"） |
| stem | TEXT | 否 | — | 题干 |
| standard_answer | TEXT | 是 | NULL | 标准答案（不下发给学生端） |
| order_num | INTEGER | 否 | 0 | 作业内排序 |

- 索引：`ix_questions_assignment_id`。

### 2.4 submissions —— 提交记录

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| id | INTEGER PK 自增 | 否 | — | 主键 |
| student_id | INTEGER FK → users.id | 否 | — | 提交学生 |
| question_id | INTEGER FK → questions.id | 否 | — | 题目 |
| status | VARCHAR(16) | 否 | `submitted` | `submitted`（已提交）\| `graded`（已诊断） |
| submitted_at | TIMESTAMP | 否 | now | 提交时间 |

- 索引：`ix_submissions_student_id`、`ix_submissions_question_id`。
- 说明：数学题的提交在接口内同步完成诊断，落库时 `status` 直接为 `graded`。

### 2.5 steps —— 作答步骤

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| id | INTEGER PK 自增 | 否 | — | 主键 |
| submission_id | INTEGER FK → submissions.id | 否 | — | 所属提交 |
| seq | INTEGER | 否 | — | 序号，**0 = 题干**（后端自动插入），1…n 为学生作答步骤 |
| text | TEXT | 否 | — | 步骤文本（seq=0 时为题干原文） |
| status | VARCHAR(16) | 否 | `pending` | `stem`（题干参考）\| `ok`（与上一步等价）\| `error`（首次不等价）\| `unparseable`（无法解析）\| `skipped`（首次出错后跳过） |

- 索引：`ix_steps_submission_id`；联合唯一 `(submission_id, seq)`（应用层保证）。

### 2.6 errors —— 错误记录（诊断核心）

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| id | INTEGER PK 自增 | 否 | — | 主键 |
| submission_id | INTEGER FK → submissions.id | 否 | — | 所属提交 |
| step_id | INTEGER FK → steps.id | 是 | NULL | 出错步骤（unparseable 也关联） |
| knowledge_point | VARCHAR(64) | 否 | — | 知识点（冗余自题目，便于聚合查询） |
| error_type | VARCHAR(16) | 否 | — | `计算失误` \| `概念混淆` \| `审题遗漏` \| `无法解析` |
| confidence | DOUBLE PRECISION | 否 | — | 置信度 0~1 |
| is_stubborn | BOOLEAN | 否 | false | 顽固误区：该生该知识点 N 天内重复出错 |
| teacher_corrected | BOOLEAN | 否 | false | 教师是否人工纠错过 |
| teacher_note | TEXT | 是 | NULL | 教师备注 |
| detail | TEXT | 是 | NULL | 人类可读的诊断说明（如"移项未变号"） |
| created_at | TIMESTAMP | 否 | now | 记录时间（顽固判断的时间依据） |

- 索引：`ix_errors_submission_id`、`ix_errors_knowledge_point`、`ix_errors_created_at`。
- 说明：`knowledge_point` 冗余存储是为了让教师端聚合查询不做多表 join；`teacher_corrected=true` 的记录是未来的回标训练数据。

### 2.7 corrections —— 订正记录

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| id | INTEGER PK 自增 | 否 | — | 主键 |
| error_id | INTEGER FK → errors.id | 否 | — | 针对的错误 |
| student_id | INTEGER FK → users.id | 否 | — | 订正学生 |
| content | TEXT | 否 | — | 订正内容 |
| is_correct | BOOLEAN | 是 | NULL | true 正确 / false 仍错 / NULL 无法判定（需教师确认） |
| note | TEXT | 是 | NULL | 判定说明 |
| submitted_at | TIMESTAMP | 否 | now | 订正时间 |

- 索引：`ix_corrections_error_id`。

### 2.8 essays —— 英语作文

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| id | INTEGER PK 自增 | 否 | — | 主键 |
| student_id | INTEGER FK → users.id | 否 | — | 学生 |
| question_id | INTEGER FK → questions.id | 是 | NULL | 关联作文题（可为空） |
| text | TEXT | 否 | — | 作文原文 |
| scores_json | TEXT | 否 | — | JSON：`{content, structure, grammar, vocabulary, expression, total}`，均为 0~100 整数 |
| grammar_issues_json | TEXT | 否 | — | JSON 数组：`[{sentence_no, sentence, issue, suggestion}]` |
| overall_comment | TEXT | 是 | NULL | 总评 |
| submitted_at | TIMESTAMP | 否 | now | 提交时间 |

- 索引：`ix_essays_student_id`。
- 说明：`scores_json` / `grammar_issues_json` 在 PostgreSQL 迁移时改为 JSONB。

### 2.9 chat_messages —— Agent 对话记录（v0.3.0 新增）

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| id | INTEGER PK 自增 | 否 | — | 主键 |
| user_id | INTEGER FK → users.id | 否 | — | 对话所属学生 |
| role | VARCHAR(16) | 否 | — | `user` \| `assistant` |
| content | TEXT | 否 | — | 消息文本 |
| created_at | TIMESTAMP | 否 | now | 发送时间 |

- 索引：`ix_chat_messages_user_id`。
- 说明：学生主页 Agent 的对话持久化；组上下文取最近 20 条，历史接口返回最近 50 条。
- **v0.6.0 起停用**：对话改走 `chat_sessions` / `chat_session_messages`（2.14 / 2.15）；本表存量数据在用户首次访问会话接口时迁入一条「之前的对话」会话后删除对应行，本表不再写入。

### 2.10 notifications —— 站内提醒（v0.3.0 新增）

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| id | INTEGER PK 自增 | 否 | — | 主键 |
| user_id | INTEGER FK → users.id | 否 | — | 接收提醒的用户 |
| type | VARCHAR(32) | 否 | — | 提醒类型，目前 `teacher_correction` |
| content | TEXT | 否 | — | 提醒文案 |
| related_submission_id | INTEGER FK → submissions.id | 是 | NULL | 关联提交（点提醒跳诊断用） |
| is_read | BOOLEAN | 否 | false | 是否已读 |
| created_at | TIMESTAMP | 否 | now | 生成时间 |

- 索引：`ix_notifications_user_id`。
- 说明：教师一键纠错成功后写入一条，提醒被纠错的学生；删除作业时关联这些提交的提醒一并级联删除。

### 2.11 verifications —— 二次验证记录（v0.4.0 新增）

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| id | INTEGER PK 自增 | 否 | — | 主键 |
| student_id | INTEGER FK → users.id | 否 | — | 做验证的学生 |
| knowledge_point | VARCHAR(64) | 否 | — | 验证的知识点 |
| source_error_id | INTEGER FK → errors.id | 是 | NULL | 触发本次验证的错题 |
| variant_json | TEXT | 否 | — | JSON：`{prompt, knowledge_point, standard_steps, answer, mode}`（mode = `strict` 已 sympy 验算 \| `practice` 练习模式） |
| status | VARCHAR(16) | 否 | `pending` | `pending`（待作答）\| `passed`（已通过）\| `failed`（未通过，可重试） |
| attempts | INTEGER | 否 | 0 | 提交作答次数 |
| created_at | TIMESTAMP | 否 | now | 创建时间 |
| completed_at | TIMESTAMP | 是 | NULL | 通过时间 |

- 索引：`ix_verifications_student_id`、`ix_verifications_knowledge_point`。
- 说明：`variant_json` 中的 `standard_steps` / `answer` 只在后端判定用，**永不下发学生端**（接口只回 `prompt`）。知识点「已修复」的唯一依据 = 该生该知识点存在一条 `status=passed` 的记录（见 api-contract 3.13 四态口径）。

### 2.12 workbooks —— 练习册知识库（v0.5.0 新增）

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| id | INTEGER PK 自增 | 否 | — | 主键 |
| teacher_id | INTEGER FK → users.id | 否 | — | 上传的教师（知识库按教师隔离） |
| title | VARCHAR(128) | 否 | — | 练习册名（默认取 PDF 文件名去扩展名） |
| file_path | VARCHAR(256) | 否 | — | 相对 UPLOAD_DIR 的路径，如 `workbooks/20261007xxxx_ab12cd34.pdf`，经 `/api/uploads/` 访问 |
| created_at | TIMESTAMP | 否 | now | 上传时间 |

- 索引：`ix_workbooks_teacher_id`。
- 说明：PDF 文件只存磁盘（UPLOAD_DIR/workbooks/，≤30MB），本表只存元信息；删除练习册时连文件一并删除。

### 2.13 assignment_ext —— 作业扩展信息（v0.5.0 新增）

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| assignment_id | INTEGER PK FK → assignments.id | 否 | — | 一份作业至多一行 |
| mode | VARCHAR(16) | 否 | `online` | `online`（线上作业）\| `offline`（线下练习册作业） |
| workbook_id | INTEGER FK → workbooks.id | 是 | NULL | 线下作业关联的练习册 |
| page_range | VARCHAR(64) | 是 | NULL | 页码/题号范围，如「第12-14页 第1-8题」 |
| deadline | TIMESTAMP | 是 | NULL | 线下作业截止时间 |

- 说明：**无 ext 行 = 线上作业**（`assignments` 老数据零迁移）；`mode=offline` 发布时才写行。删除作业时应用层一并删除 ext 行；删除练习册时把引用它的 `workbook_id` 置 NULL（只更新本新表，不动老表）。
- v0.6.0 备注：练习册封面图不落库——上传时把 PDF 第一页渲染为 `UPLOAD_DIR/covers/{workbook_id}.jpg`（列表时缺失则懒生成），按文件名与本表 id 约定关联。

### 2.14 chat_sessions —— Agent 对话会话（v0.6.0 新增）

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| id | INTEGER PK 自增 | 否 | — | 主键 |
| user_id | INTEGER FK → users.id | 否 | — | 会话所属用户（学生/教师共用，按 user_id 隔离） |
| title | VARCHAR(128) | 否 | `新对话` | 会话标题；首条用户消息到达时自动改为该消息前 20 字；迁移生成的会话为「之前的对话」 |
| created_at | TIMESTAMP | 否 | now | 创建时间 |
| updated_at | TIMESTAMP | 否 | now | 最近活动时间（每次追加消息刷新）；「当前会话」= 本人 updated_at 最大的一条 |

- 索引：`ix_chat_sessions_user_id`。
- 说明：v0.6.0 对话会话化。旧表 `chat_messages` 停用：用户首次访问会话接口且尚无任何会话时，其旧消息被整体复制为一条「之前的对话」会话后删除旧行（防重复迁移）。

### 2.15 chat_session_messages —— 会话内消息（v0.6.0 新增）

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| id | INTEGER PK 自增 | 否 | — | 主键 |
| session_id | INTEGER FK → chat_sessions.id | 否 | — | 所属会话 |
| role | VARCHAR(16) | 否 | — | `user` \| `assistant` |
| content | TEXT | 否 | — | 消息文本 |
| created_at | TIMESTAMP | 否 | now | 发送时间 |

- 索引：`ix_chat_session_messages_session_id`。
- 说明：上下文组装只取当前会话最近 20 条，会话之间隔离；删除会话时应用层一并删除其消息。

### 2.16 chat_session_message_mistake_links —— 助手消息关联历史错题（v0.13.13 新增）

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| message_id | INTEGER PK，FK → chat_session_messages.id | 否 | — | 关联的助手回复；每条回复最多关联一条历史错题 |
| error_id | INTEGER | 否 | — | 关联的历史错误记录 ID；由服务层校验学生归属、审核状态和归档状态 |
| created_at | TIMESTAMP | 否 | now | 关联创建时间 |

- 索引：`ix_chat_session_message_mistake_links_error_id`。
- 说明：`error_id` 按逻辑关系保存，不设数据库外键；删除教师作业时由应用层同步清理关联。消息恢复时再校验错题仍属于当前学生且可见。

### 2.17 submission_images —— 学生作答原图关联（v0.13.14 新增）

| 字段 | 类型 | 可空 | 默认 | 说明 |
|---|---|---|---|---|
| submission_id | INTEGER PK，FK → submissions.id | 否 | — | 对应的学生提交；每份提交最多关联一张原图 |
| file_path | VARCHAR(512) | 否 | — | UPLOAD_DIR 下的相对路径 |
| file_name | VARCHAR(255) | 否 | — | 学生上传时的文件名 |
| created_at | TIMESTAMP | 否 | now | 关联创建时间 |

- 说明：图片文件仍存放在 `UPLOAD_DIR`，本表只存提交与文件的对应关系。删除作业时应用层先清理关联行；既有自主上传提交缺少此行时，审核队列可从提交前的对话图片回溯显示缩略图。

## 3. 关系图（ER，文本版）

```
users 1 ──< assignments (created_by)
users 1 ──< submissions (student_id)
users 1 ──< corrections (student_id)
users 1 ──< essays (student_id)
users 1 ──< verifications (student_id)
users 1 ──< workbooks (teacher_id)
users 1 ──< chat_sessions (user_id)
errors 1 ──< verifications (source_error_id, 可空)
chat_sessions 1 ──< chat_session_messages (session_id)
chat_session_messages 1 ─── chat_session_message_mistake_links (message_id)
submissions 1 ─── submission_images (submission_id, 1:0..1)

assignments 1 ──< questions (assignment_id)
assignments 1 ─── assignment_ext (assignment_id, 1:0..1)
workbooks 1 ──< assignment_ext (workbook_id, 可空)
questions 1 ──< submissions (question_id)
questions 1 ──< essays (question_id, 可空)

submissions 1 ──< steps (submission_id)
submissions 1 ──< errors (submission_id)
steps 1 ──< errors (step_id, 可空)
errors 1 ──< corrections (error_id)
```

## 4. 顽固误区判定口径（is_stubborn）

判定 SQL 等价逻辑：

```sql
-- 新 error 记为 E（student_id=S，knowledge_point=K，created_at=T）
SELECT COUNT(*) FROM errors e
JOIN submissions s ON s.id = e.submission_id
WHERE s.student_id = S
  AND e.knowledge_point = K
  AND e.id <> E.id
  AND e.created_at >= T - INTERVAL 'N days';   -- N 默认 30，可配 STUBBORN_WINDOW_DAYS
-- COUNT >= 1 → is_stubborn = true
```

即：同一学生、同一知识点、过去 N 天内已有 ≥1 条错误记录 → 本次记为顽固误区。

## 5. 演示数据（seed.py 预置）

| 用户 | role | student_no |
|---|---|---|
| 陈老师 | teacher | NULL |
| 林小夏 | student | S2026001 |
| 陈默 | student | S2026002 |

作业「第一周数学+英语作业」：

| # | subject | knowledge_point | stem | standard_answer |
|---|---|---|---|---|
| 1 | math | 一元一次方程 | 解方程：2x+3=7 | x=2 |
| 2 | math | 完全平方公式 | 解方程：(x+1)²=9 | x=2 或 x=-4 |
| 3 | math | 去括号 | 解方程：2(x-3)=10 | x=8 |
| 4 | english | 英语写作 | Write a short paragraph about your weekend (60-80 words). | NULL |

历史错误（走真实诊断管线生成，再回拨 `created_at`）：

1. 林小夏 20 天前做第 1 题：`["2x+3=7", "2x=7+3", "2x=10", "x=5"]` → step1 移项未变号 → `概念混淆`。**该记录用于演示：当她再次在"一元一次方程"出错时，新 error 的 `is_stubborn=true`。**
2. 陈默 5 天前做第 3 题：`["2(x-3)=10", "2x-3=10", "2x=13", "x=6.5"]` → step1 分配律漏乘 → `概念混淆`（教师已备注 `teacher_corrected=true`，演示回标）。

## 6. PostgreSQL 迁移 checklist

1. `scores_json`、`grammar_issues_json`：TEXT → JSONB。
2. 所有 `TIMESTAMP` 列：→ TIMESTAMPTZ；Python 侧改用 `datetime.now(timezone.utc)`。
3. 自增主键：`INTEGER GENERATED ALWAYS AS IDENTITY`。
4. 补 `ON DELETE CASCADE`（submissions→steps/errors 等，按业务定）。
5. `DATABASE_URL` 改为 `postgresql+psycopg2://...` 即可，SQLAlchemy 代码零改动。

## 7. 变更记录

| 版本 | 日期 | 说明 |
|---|---|---|
| v0.1.0 | 2026-10-06 | 初版冻结 |
| v0.2.0 | 2026-10-07 | 无表结构变更：拍照图片走文件存储（UPLOAD_DIR），不新建表、不给现有表加列 |
| v0.2.1 | 2026-10-07 | 无表结构变更：学习报告/错题时间线均为现有表聚合查询 |
| v0.3.0 | 2026-10-07 | 新增两张表：`chat_messages`（Agent 对话记录）、`notifications`（站内提醒）；不改任何现有表/列。删除作业走应用层级联（见 api-contract 4.10） |
| v0.4.0 | 2026-10-07 | 新增一张表：`verifications`（二次验证记录）；不改任何现有表/列。知识点状态口径升级为四态（见 api-contract 3.13），「已修复」只认 verifications 的 passed 记录 |
| v0.5.0 | 2026-10-07 | 新增两张表：`workbooks`（练习册知识库）、`assignment_ext`（作业发布模式扩展）；不改任何现有表/列。教师 Agent 对话复用 `chat_messages`（按 user_id 区分），提醒未交复用 `notifications`（新 type 值 `teacher_reminder`） |
| v0.6.0 | 2026-10-07 | 新增两张表：`chat_sessions`（对话会话）、`chat_session_messages`（会话内消息）；不改任何现有表/列。`chat_messages` 停用（旧数据首次访问会话接口时迁移为「之前的对话」会话后清空对应行）。练习册封面走文件约定（UPLOAD_DIR/covers/{id}.jpg），不给 `workbooks` 加列 |
| v0.13.13 | 2026-10-12 | 新增 `chat_session_message_mistake_links`，持久化助手回复与历史错题的关联；不改现有表和列。 |
| v0.13.14 | 2026-10-12 | 新增 `submission_images`，关联学生作答原图与提交记录，供教师待审核作业卡展示。 |
| v0.13.315 | 2026-10-22 | 新增 `subject_knowledge_passages`，保存学科教学资料父子片段和 PDF 页码；向量存入可重建的 Milvus 索引，不改变已有资料表。 |

## 8. 学科 RAG 片段（v0.13.315）

`subject_knowledge_passages` 关联已有 `subject_knowledge_chunks` 资料，启动时自动创建，旧资料可立即以临时片段检索，重建索引时再持久化。

| 字段 | 类型 | 说明 |
|---|---|---|
| id | Integer PK | SQLite AUTOINCREMENT，避免已提交片段 ID 被重用造成旧向量错误引用 |
| document_id | Integer FK | 对应 `subject_knowledge_chunks.id`，应用层删除时同时清理片段 |
| parent_index / chunk_index | Integer | 父块号与资料内子块顺序；`document_id + chunk_index` 唯一索引 |
| content / parent_content | Text | 子块用于召回，父块用于恢复教学上下文 |
| page_number | Integer nullable | PDF 原始物理页号（从 1 开始）；手工文本为 null |

Milvus 集合保存片段 `id`、`document_id`、`subject`、`embedding_model` 和 `vectors`，同时按学科和模型过滤，使用 COSINE 相似度。查询结果必须再通过关系库的学科和存活状态校验；向量属于派生索引，关系库是原文与页码的依据。本地事务提交后才进行远程向量同步，避免外部网络延迟占用 SQLite 写锁。
