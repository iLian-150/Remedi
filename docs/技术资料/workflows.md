# 工作流简图

## 教师发布作业 → 学生答题 → 后台 AI 批改

![教师发布作业、学生答题与 AI 批改流程图](技术图/workflow.png)

```mermaid
flowchart TD
    T[教师创建作业\n录入题目并选择班级] --> P[发布作业]
    P --> A[(作业与题目写入 SQL)]
    A --> L[学生端获取待完成作业]
    L --> W[学生逐题作答\n文字或作答图片]
    W --> S[逐题保存作答草稿\n此时不启动批改]
    S --> C{所有题目都已作答?}
    C -->|否| W
    C -->|是| Submit[学生点击提交作业]
    Submit --> V[服务端校验作业、题目和答案]
    V --> Q[创建或更新批改任务\n状态 queued]
    Q --> DB[(SQL 持久化答案与任务)]
    DB --> Worker[服务端 worker 领取任务]
    Worker --> Grade[逐题识别与 AI 诊断]
    Grade --> CP[记录逐题检查点\n重试时复用已成功结果]
    CP --> More{还有题目未处理?}
    More -->|是| Grade
    More -->|否| Save[集中写入批改结果\n分数 / 步骤 / 错因 / 审核状态]
    Save --> Done[任务标记 completed]
    Done --> Student[学生端查询进度并查看结果]
    Done --> Teacher[教师端查看本次作业学情]
    Student --> Correction[学生后续订正与验证]

    Grade -. 任务异常 .-> Retry[任务重新排队\n指数退避，最长间隔 300 秒]
    Retry --> DB
    DB -. 应用重启时恢复未完成任务 .-> Worker
    Student -. 页面轮询进度；退出账号不取消任务 .-> StatusAPI[作业状态 API]
    StatusAPI --> DB
```

### 作业批改状态

`draft → queued → processing → completed` 是常见路径。若后台处理遇到异常，任务自动回到队列并设置下一次尝试时间；已成功题目的检查点可在重试时复用。浏览器负责提交答案和查询状态，不负责维持批改任务。

## 多 Agent 学科批改

![Remedi 多 Agent 学科批改流程图](技术图/multi_agent_grading.png)

```mermaid
flowchart LR
    subgraph Chat[学习助手文字批改]
        UserText[学生提交题目与本人作答] --> Router[LangGraph 判断意图与学科]
        Router --> Tool[diagnose_student_text_work]
    end

    subgraph Assignment[整份作业批改]
        Submit[学生提交整份作业] --> Job[(SQL 持久化批改任务)]
        Job --> Worker[后台 worker 逐题处理]
        Worker --> Answer[题干与学生文字或图片作答]
    end

    Tool --> SubjectAgent[按学科选择专属批改 Agent]
    Answer --> SubjectAgent
    Knowledge[对应学科知识库\nBM25 + 可选 Milvus] --> SubjectAgent
    SubjectAgent --> Provider[模型返回结构化逐步判断]
    Provider --> Validate[校验正误、理由与置信度]
    Validate --> Save[保存 Submission / Steps / Errors]
    Save --> Score[计算 AI 评分]
    Score --> Student[学生查看讲解、错题与订正]
    Score --> Review{是否需要教师复核?}
    Review -->|是| Teacher[教师复核并修正结果]
    Review -->|否| Complete[批改完成]
    Teacher --> Complete
```

当前“多 Agent”指由路由按学科选择对应的专属批改 Agent，并提供该学科的知识库上下文；整份作业由后台 worker 按题逐个调度。一次作答由匹配的学科 Agent 处理，不是多个模型并行评分或投票。

常用接口：

- 教师发布：`POST /api/teacher/assignments`
- 学生查看作业：`GET /api/student/assignments`
- 学生逐题暂存：`PUT /api/student/assignments/{assignment_id}/answers/{question_id}`
- 学生提交整份作业：`POST /api/student/assignments/{assignment_id}/submit`
- 学生查看批改进度：`GET /api/student/assignments/{assignment_id}/grading-status`
- 教师查看作业学情：`GET /api/teacher/assignments/{assignment_id}/analytics`

### 截止时间与允许修改

整份作业提交接口会在答案齐全后把批改任务放入后台队列。代码中另有逐题提交、作文等提交路径：教师若开启“允许修改”并设置截止时间，截止前的提交可能按规则延迟诊断，到期扫描任务约每分钟执行一次。查看具体页面为何等待时，应先确认作业模式、截止时间和 `allow_revision` 设置；这项规则不等于普通整份作业任务需要用户保持在线。

## 教师导入学科资料

```mermaid
flowchart LR
    Upload[教师上传资料] --> File[原文件写入私有目录]
    Upload --> Job[(SQL 创建导入任务)]
    Job --> Worker[后台知识导入 worker]
    Worker --> Extract[提取正文并记录处理进度]
    Extract --> Chunks[切分并写入 SQL 知识片段]
    Chunks --> Index{Milvus 可用?}
    Index -->|是| Vector[同步向量索引]
    Index -->|否| BM25[保留关键词检索\n向量索引待后续同步]
    Vector --> Complete[任务完成]
    BM25 --> Complete
    Complete --> Search[学科 Agent 检索资料并回答]
```

SQL 保存知识内容和任务进度，Milvus 只承担可选的向量索引。Milvus 同步不可用时可回退到 BM25 关键词检索；知识导入任务同样由服务端持久化并在启动时恢复。
