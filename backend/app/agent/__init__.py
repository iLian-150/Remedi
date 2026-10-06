# 主页交互 Agent（v0.3.0）：基于 LangGraph 的数学辅导对话。
# - graph.py：StateGraph 组图（agent 节点 + ToolNode + 条件边）
# - tools.py：查本人待办/学习报告/知识点错题三件工具（身份从上下文注入）
# - prompts.py：系统提示词（辅导老师人设 + 学生上下文摘要注入）
# - mock_agent.py：无凭证/调用失败时的规则回复兜底（调真实数据函数拼模板）
