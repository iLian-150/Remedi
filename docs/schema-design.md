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

## 3. 关系图（ER，文本版）

```
users 1 ──< assignments (created_by)
users 1 ──< submissions (student_id)
users 1 ──< corrections (student_id)
users 1 ──< essays (student_id)

assignments 1 ──< questions (assignment_id)
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
