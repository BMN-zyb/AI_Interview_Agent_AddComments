"""
技术对比技能：两个技术方案的对比分析
★ 使用方式：/compare <技术A> vs <技术B>
"""
# 启用延迟注解求值，支持前向引用并避免导入顺序问题
from __future__ import annotations

# 标准库类型注解：Any 表示任意类型，Dict 描述会话状态字典
from typing import Any, Dict

# 导入技能基类，本技能继承它以复用 LLM 调用与日志能力
from skills.base_skill import BaseSkill

# 对比提示词模板：要求 LLM 从 5 个维度对比并输出 JSON；__SUBJECTS__ 为对比对象占位符
# 模板中 {{ }} 为字面花括号转义，避免被误当作格式化字段
PROMPT = """\
请对以下两个技术方案进行专业对比分析：

对比对象：__SUBJECTS__

请从以下 5 个维度分析，并给出综合建议：
1. 性能表现
2. 实现复杂度
3. 可维护性
4. 适用场景
5. 面试常考点

输出 JSON：
{{
  "subject_a": "技术A名称",
  "subject_b": "技术B名称",
  "comparison": [
    {{"dimension": "维度名", "a": "A的表现", "b": "B的表现", "winner": "a或b或tie"}}
  ],
  "summary": "综合建议（100字以内）",
  "interview_tips": "面试中如何回答对比题的技巧"
}}
"""

# 使用提示文本：当用户未提供对比对象时返回，给出示例用法
USAGE_HINT = """\
🔀 技术对比使用方式：
  /compare RAG vs Fine-tuning
  /compare Redis vs Memcached
  /compare BM25 vs 向量检索
"""


class CompareSkill(BaseSkill):
    # 技能名，作为注册表查找键
    name = "compare"
    # 技能描述，用于帮助/展示
    description = "技术对比：多维度对比两个技术方案"
    # 触发关键词，用于意图识别路由到本技能
    trigger_keywords = ["对比", "compare", "区别", "差异"]

    def run(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """执行技术对比：解析对比对象，调用 LLM 生成多维度对比并渲染成表格写回状态。

        参数:
            state: 会话状态字典，需包含 user_input（形如 "A vs B"）。
        返回:
            更新后的会话状态字典，agent_reply 为对比表格或使用提示。
        """
        # 读取用户原始输入并去除首尾空白；缺失时用空串兜底
        user_input = state.get("user_input", "").strip()

        # 移除 /compare 前缀
        # 若输入以 /compare 开头（忽略大小写），切掉前 8 个字符的前缀并去空白，得到纯对比对象
        if user_input.lower().startswith("/compare"):
            user_input = user_input[8:].strip()

        # 对比对象为空：返回使用提示并提前结束
        if not user_input:
            state["agent_reply"] = USAGE_HINT
            return state

        # 将清洗后的输入作为对比对象文本
        subjects = user_input
        # 用对比对象替换提示词模板中的占位符，生成最终提示
        prompt = PROMPT.replace("__SUBJECTS__", subjects)
        # 调用 LLM 并解析为 JSON 字典；system_prompt 传空串
        parsed = self.invoke_llm_json(prompt, "")

        # 取出技术 A 名称，缺失时回退为 "A"
        subject_a = parsed.get("subject_a", "A")
        # 取出技术 B 名称，缺失时回退为 "B"
        subject_b = parsed.get("subject_b", "B")
        # 取出各维度对比行列表，缺失时为空列表
        rows = parsed.get("comparison", [])
        # 取出综合建议文本，缺失时为空串
        summary = parsed.get("summary", "")
        # 取出面试技巧文本，缺失时为空串
        tips = parsed.get("interview_tips", "")

        # 构建对比表格文本
        # 初始化输出行列表，首行为标题（加粗显示两个对比对象）
        lines = [f"🔀 **{subject_a}** vs **{subject_b}** 对比分析\n"]
        # 追加表头行，用 <数字 做左对齐定宽排版，使各列上下对齐
        lines.append(f"{'维度':<12} {''+subject_a:<20} {''+subject_b:<20} {'胜者':<6}")
        # 追加一条分隔横线（重复 60 个横线字符）
        lines.append("─" * 60)
        # 胜者代码到展示文本的映射：a/b 映射为对应技术名，tie 映射为"平局"
        winner_map = {"a": subject_a, "b": subject_b, "tie": "平局"}
        # 遍历每一行对比数据，逐条渲染成定宽对齐的文本行
        for r in rows:
            # 根据该行 winner 代码查出展示文本，未知值兜底为"平局"
            winner = winner_map.get(r.get("winner", "tie"), "平局")
            # 将维度、A 表现、B 表现、胜者四列按定宽左对齐拼成一行追加（多行 f-string 拼接同一字符串）
            lines.append(
                f"{r.get('dimension',''):<12} "
                f"{r.get('a',''):<20} "
                f"{r.get('b',''):<20} "
                f"{winner:<6}"
            )

        # 若存在综合建议，追加展示
        if summary:
            lines.append(f"\n💡 综合建议：{summary}")
        # 若存在面试技巧，追加展示
        if tips:
            lines.append(f"\n🎯 面试技巧：{tips}")

        # 用换行拼接所有行作为最终回复写入状态
        state["agent_reply"] = "\n".join(lines)
        # 记录日志，标明本次对比的对象
        self.logger.info(f"CompareSkill 对比：{subjects}")
        # 返回更新后的会话状态
        return state