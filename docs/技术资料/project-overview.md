# 项目功能总览

![Remedi 学习平台项目功能总览](技术图/project_feature_overview.png)

总图按教师端、学生端、核心学习闭环、AI 与后台服务、技术底座归纳项目主要功能。教师先用 AI 整理作业草稿，再检查并手动发布；学生答题提交后，由持久化后台任务逐题分派对应学科 Agent 批改。错题经订正和变式验证后更新学生学习记忆，供学习助手个性化答疑和教师学情分析使用。

主页学习助手会话与错题本的题目专属讲解会话分别保存，互不串用。当前学科批改是逐题选择匹配的学科 Agent，不是多个模型并行投票。已经提交的后台任务不依赖学生保持登录；应用进程停止时任务暂停，应用重新启动后恢复处理。

```mermaid
flowchart TB
    subgraph Teacher[教师端]
        TeacherAssistant[AI 助手\n班级数据 / 教学问答 / 作业草稿]
        ClassStudent[班级与学生\n班级管理 / 名册 / 学生画像]
        AssignmentManage[作业管理\nAI 辅助组题 / 线上线下发布 / 编辑提醒 / 学情]
        GradingReview[AI 批改\n进度 / 诊断详情 / 教师复核]
        Dashboard[班级总览\n错误率 / 错因分布 / 教学建议]
        Materials[教学资料\n上传 / 导入 / 学科知识库]
    end

    subgraph Student[学生端]
        StudentAssistant[学习助手\n文字问答 / 拍照答疑 / 主页对话]
        StudentAssignment[作业学习\n查看 / 文字或图片作答 / 提交 / 批改结果]
        MistakeBook[错题本\n学科归类 / 题目专属讲解（独立会话）]
        Correction[订正与验证\n重新作答 / 订正提交 / 变式验证]
        Profile[学习档案\n学科报告 / 学习画像 / 知识点记忆]
    end

    subgraph Learning[核心学习闭环]
        Draft[教师 AI 助手生成作业草稿] --> Review[教师检查并确认发布]
        Review --> Published[作业对学生开放]
        Published --> Answer[学生逐题作答并提交]
        Answer --> Job[(SQL 持久化批改任务)]
        Job --> Worker[后台 Worker 逐题处理]
        Worker --> Route[按题目学科路由]
        Route --> Agent[对应学科 Agent]
        Agent --> Diagnosis[结构化诊断与评分]
        Diagnosis --> Save[保存作答 / 步骤 / 错因]
        Save --> Mistake[错题沉淀]
        Mistake --> Fix[订正与变式验证]
        Fix --> Memory[(学生长期学习记忆)]
        Memory --> Personalized[学习助手个性化上下文]
        Save --> ClassAnalytics[教师查看作业与班级学情]
    end

    TeacherAssistant --> Draft
    AssignmentManage --> Draft
    Materials --> ImportWorker[知识资料导入 Worker]
    ImportWorker --> RAG[学科知识检索\nBM25 + 可选 Milvus]
    RAG --> Agent
    Diagnosis --> GradingReview
    ClassAnalytics --> Dashboard
    ClassAnalytics --> ClassStudent
    Personalized --> StudentAssistant
    StudentAssignment --> Answer
    Save --> MistakeBook
    Fix --> Profile
    ClassStudent --> ClassAnalytics

    subgraph Platform[技术底座]
        Frontend[Vue 3 + TypeScript]
        API[FastAPI\n登录鉴权与业务 API]
        SQL[(SQL\n用户 / 班级 / 作业 / 作答 / 批改 / 订正 / 记忆)]
        Files[(私有文件\n作答图片 / 教学资料)]
        Models[外部 AI 模型服务]
    end

    Frontend --> API
    API --> SQL
    API --> Files
    API --> Models
    Worker --> SQL
    ImportWorker --> SQL
    Agent --> Models
```
