# Remedi 技术资料

本目录整理项目当前实现，供开发、排查和后续维护使用。架构和流程以代码为准；接口或实现调整后，请一并更新相关图示。

## 文档

- [系统架构](architecture.md)：前端、API、后台任务、数据库、文件存储、知识检索和模型服务之间的关系。
- [工作流简图](workflows.md)：教师发布作业、学生答题与提交、后台 AI 批改，以及知识库导入。
- [数据与接口索引](data-and-interfaces.md)：关键数据表、接口入口和聊天、学习记忆的数据边界。

架构图和工作流图使用 ImageGen 生成，图片统一放在 [技术图](技术图/) 文件夹中：[架构图 PNG](技术图/architecture.png)、[主工作流 PNG](技术图/workflow.png)、[多 Agent 批改 PNG](技术图/multi_agent_grading.png)、[学习记忆设计 PNG](技术图/learning_memory_design.png)。对应的 Mermaid 图源和正文保留精确的组件、接口与流程说明。

## 阅读约定

- 图表使用 Mermaid，源文件就在本目录的 Markdown 中，可直接编辑。
- `backend/app/` 和 `frontend/src/` 是主要实现位置；接口细节优先查看 [API 契约](../api-contract.md) 和 [数据库设计](../schema-design.md)。
- 默认数据库为 SQLite，也可以配置 PostgreSQL。Milvus 是可选的向量检索组件，不能把它当作业务记录的唯一存储。
- 不要把 `.env`、模型凭证、真实用户数据或私有上传内容写入这些文档。
- `deploy/nginx.conf` 是容器部署示例；线上机器的实际拓扑以部署环境配置为准。
