"""
CLI 入口：基于 typer + rich
"""
# 启用 PEP 563 延迟注解求值：使得形如 `str | None` 的类型注解在旧版本 Python 上
# 也能写成字符串而不会在导入时立即求值，避免运行时报错。
from __future__ import annotations

# typer：声明式命令行框架，用于把 Python 函数包装成 CLI 子命令。
import typer
# rich.console.Console：富文本输出的核心对象，负责把带样式标记的文本渲染到终端。
from rich.console import Console
# rich.panel.Panel：把内容包裹进带边框的面板里，用于突出展示标题区块。
from rich.panel import Panel
# rich.prompt.Prompt：在终端交互式地向用户索取输入（带提示文案）。
from rich.prompt import Prompt
# rich.table.Table：渲染表格，用于展示评分、主题表现、仓库列表等结构化数据。
from rich.table import Table
# rich.box：预设的表格/面板边框样式集合（如 ROUNDED、SIMPLE 等）。
from rich import box

# 项目内部模块：日志初始化函数，用于在命令执行前配置统一的日志格式与级别。
from config.logging import setup_logger

# 创建 typer 应用对象：name 为 CLI 程序名，help 为顶层帮助说明；所有子命令挂在其上。
app    = typer.Typer(name="interview-agent", help="AI 模拟面试官 CLI")
# 创建全局 rich 控制台对象，整个模块的所有终端输出都通过它完成，保证样式一致。
console = Console()

# 技能触发词映射表：把用户输入的斜杠命令前缀映射为内部技能名称（skill_name）。
# 用户在答题过程中输入这些前缀即可临时调用对应技能而不打断面试主流程。
SKILL_TRIGGERS = {
    "/quiz":    "quiz",
    "/teach":   "teach",
    "/project": "project",
    "/compare": "compare",
}

# 技能使用提示文案：每轮提问后都会打印，提醒用户可用的技能命令及退出方式。
# 使用 rich 的 [dim] 标记让提示以暗色显示，避免喧宾夺主。
SKILL_HINT = (
    "\n[dim]💡 技能：/quiz <主题> 测验 | /teach <概念> 讲解 | "
    "/project <描述> 提炼亮点 | /compare <A> vs <B> 对比 | q 退出[/dim]"
)

# 结束/退出关键词集合：用户输入其中任意一个即视为主动中断或结束面试。
# 同时包含中英文常见说法，提升交互的容错性。
FINISH_KEYWORDS = ("q", "quit", "exit", "退出", "结束面试", "结束", "end", "stop")


def _detect_skill(user_input: str):
    """检测用户输入是否为技能命令。

    参数:
        user_input: 用户在终端输入的原始字符串。
    返回:
        若匹配到某个技能前缀，返回元组 (技能名, 去掉前缀后的参数文本)；
        否则返回 None，表示这是一次普通的答题输入。
    """
    # 去除首尾空白并转小写，用于大小写不敏感地匹配技能前缀。
    stripped = user_input.strip().lower()
    # 遍历所有已注册的技能前缀，逐一判断输入是否以该前缀开头。
    for prefix, skill_name in SKILL_TRIGGERS.items():
        # 命中某个前缀：说明用户想调用该技能。
        if stripped.startswith(prefix):
            # 从「原始输入」（保留大小写）中截掉前缀部分，得到技能的实际参数文本。
            # 注意基于 user_input 而非 stripped 切片，以免破坏参数中的大小写。
            cleaned = user_input.strip()[len(prefix):].strip()
            # 返回技能名与清洗后的参数，供上层调用对应技能。
            return skill_name, cleaned
    # 未匹配任何技能前缀，返回 None 表示普通输入。
    return None


def _run_skill(graph, state: dict, skill_name: str, skill_input: str) -> dict:
    """执行一次技能调用，并把结果渲染到终端。

    参数:
        graph: 已编译的 LangGraph 工作流对象，用于驱动一次技能推理。
        state: 当前面试会话状态字典（不会被本函数原地污染关键字段）。
        skill_name: 要调用的技能名称（如 quiz/teach/project/compare）。
        skill_input: 传给该技能的参数文本。
    返回:
        更新后的会话状态字典（写回了最新的 skill_state）。
    """
    # 基于当前 state 复制一份临时状态，避免直接修改主流程的 intent 等字段。
    skill_state = dict(state)
    # 将意图标记为「使用技能」，让工作流路由到技能处理分支。
    skill_state["intent"]     = "use_skill"
    # 指定本次要执行的具体技能名称。
    skill_state["skill_name"] = skill_name
    # 把用户提供的参数作为技能的输入文本。
    skill_state["user_input"] = skill_input

    # 调用工作流执行技能推理，得到包含技能回复的结果状态。
    result = graph.invoke(skill_state)
    # 取出技能生成的回复文本；缺失时回退为空字符串，避免后续渲染报错。
    reply  = result.get("agent_reply", "")

    # 用洋红色面板展示技能结果，标题标明当前技能名，视觉上与面试主流程区分开。
    console.print(Panel(
        reply,
        title=f"🛠️  Skill: {skill_name}",
        border_style="magenta",
        padding=(1, 2),
    ))

    # 把技能产生的上下文（skill_state）写回主状态，以便后续技能调用可累积记忆。
    state["skill_state"] = result.get("skill_state", {})
    # 返回更新后的主状态，交由调用方继续面试流程。
    return state


def _ensure_list(val) -> list:
    """
    ★ 核心修复：确保字段为字符串列表，防止对字符串逐字遍历。
    - list  → 过滤空项
    - str   → 按分号/换行拆分为列表
    - other → 包装为单元素列表
    """
    # 情况一：已是列表 —— 把每个元素转字符串并去空白，过滤掉空白项后返回。
    if isinstance(val, list):
        return [str(i).strip() for i in val if str(i).strip()]
    # 情况二：是字符串 —— 需要拆分成列表，否则直接遍历会被逐个字符迭代。
    if isinstance(val, str):
        # 先去除首尾空白，便于判断是否为空。
        val = val.strip()
        # 空字符串直接返回空列表，避免拆分出无意义的空项。
        if not val:
            return []
        # 在函数内部按需导入 re，避免为这一处拆分在模块顶层引入依赖。
        import re
        # 以中文分号「；」、英文分号「;」或换行符作为分隔符拆分（连续分隔符视为一个）。
        parts = re.split(r"[；;\n]+", val)
        # 去空白并过滤空项后返回，得到干净的字符串列表。
        return [p.strip() for p in parts if p.strip()]
    # 情况三：其他类型 —— 非空则包装成单元素列表，None/假值则返回空列表。
    return [str(val)] if val else []


def _print_report(report: dict) -> None:
    """渲染最终面试评估报告（总分、六维评分、主题表现、优劣势分析）。

    参数:
        report: 工作流产出的评估报告字典；为空时直接跳过不渲染。
    返回:
        None（仅产生终端输出，无返回值）。
    """
    # 报告为空（None 或空字典）时无内容可展示，提前返回。
    if not report:
        return

    # 录用建议英文枚举 → 带颜色与图标的中文展示文案的映射表。
    rec_map = {
        "strong_hire": "[bold green]强烈推荐 ✅[/]",
        "hire":        "[green]推荐录用 ✅[/]",
        "weak_hire":   "[yellow]勉强推荐 ⚠️[/]",
        "no_hire":     "[red]不推荐 ❌[/]",
    }
    # 取出报告中的录用建议并映射为展示文案；
    # 若枚举不在映射表中，则回退展示原始值（仍取不到则显示「-」）。
    rec = rec_map.get(
        report.get("recommendation", ""),
        report.get("recommendation", "-")
    )

    # 用青色面板展示报告概览：总分、录用建议、总评与面试官寄语。
    console.print(Panel(
        f"[bold]总分：{report.get('overall_score', '-')} / 100[/]    "
        f"录用建议：{rec}\n\n"
        f"[bold cyan]📝 总评：[/]\n{report.get('summary', '')}\n\n"
        f"[bold cyan]💬 面试官寄语：[/]\n{report.get('interviewer_comment', '')}",
        title="📊 面试评估报告",
        border_style="cyan",
        padding=(1, 2),
    ))

    # ── 六维能力评分 ──────────────────────────────────────────────────────────
    # 取出六维能力的分项得分字典；不存在则为空字典，跳过该表格。
    dim_scores = report.get("dimension_scores", {})
    if dim_scores:
        # 构建六维评分表格，设置标题、圆角边框与表头样式。
        dim_table = Table(
            title="🎯 六维能力评分",
            box=box.ROUNDED,
            border_style="blue",
            header_style="bold blue",
        )
        # 依次添加三列：能力维度名称、得分、评级（含对齐方式与列宽）。
        dim_table.add_column("能力维度",   style="cyan",    width=22)
        dim_table.add_column("得分",       justify="center", width=8)
        dim_table.add_column("评级",       justify="center", width=10)

        # 六维能力字段名（英文 key）→ 中文显示名的映射表。
        dim_name_map = {
            "technical_knowledge":  "技术知识掌握度",
            "problem_solving":      "问题解决能力",
            "system_design":        "系统设计能力",
            "communication":        "表达与沟通能力",
            "practical_experience": "实战经验丰富度",
            "learning_ability":     "学习潜力与适应力",
        }

        def _level(s):
            """把数值分数（0~10）映射为带颜色的中文评级标签。

            参数 s: 单项能力得分，可能为数值或缺失占位符。
            返回: 形如「[green]优秀[/]」的 rich 标记字符串；非数值返回「-」。
            """
            # 非数值（如缺失时的「-」）无法比较大小，直接返回占位符。
            if not isinstance(s, (int, float)): return "-"
            # 分段映射：8 分及以上为优秀。
            if s >= 8: return "[green]优秀[/]"
            # 6~8 分为良好。
            if s >= 6: return "[yellow]良好[/]"
            # 4~6 分为一般。
            if s >= 4: return "[orange1]一般[/]"
            # 4 分以下为待提升。
            return "[red]待提升[/]"

        # 遍历六个维度，按映射表取出中文名与对应得分，逐行写入表格。
        for key, cn in dim_name_map.items():
            # 取该维度的得分，缺失则用「-」占位。
            s = dim_scores.get(key, "-")
            # 添加一行：中文维度名、得分（转字符串）、由 _level 计算的评级。
            dim_table.add_row(cn, str(s), _level(s))
        # 输出渲染好的六维评分表格。
        console.print(dim_table)

    # ── 各主题表现 ────────────────────────────────────────────────────────────
    # 取出按技术主题统计的表现列表；为空则跳过该表格。
    topic_perf = report.get("topic_performance", [])
    if topic_perf:
        # 构建主题表现表格，使用 SIMPLE_HEAVY 边框样式。
        tp_table = Table(
            title="📌 各技术主题表现",
            box=box.SIMPLE_HEAVY,
            border_style="blue",
            header_style="bold",
        )
        # 添加三列：主题名、表现评级、文字点评。
        tp_table.add_column("主题",  style="cyan", width=20)
        tp_table.add_column("表现",  justify="center", width=10)
        tp_table.add_column("点评",  width=40)
        # 主题表现英文枚举 → 带颜色图标的中文文案映射表。
        perf_map = {
            "good":    "[green]良好 ✅[/]",
            "average": "[yellow]一般 ➖[/]",
            "weak":    "[red]薄弱 ❌[/]",
        }
        # 遍历每个主题的表现记录，逐行写入表格。
        for tp in topic_perf:
            # 把表现枚举映射为中文文案；未知值回退为原始值（再缺失则「-」）。
            perf = perf_map.get(tp.get("performance", ""), tp.get("performance", "-"))
            # 添加一行：主题名、表现文案、点评文本（缺失字段均以「-」占位）。
            tp_table.add_row(
                tp.get("topic",   "-"),
                perf,
                tp.get("comment", "-"),
            )
        # 输出渲染好的主题表现表格。
        console.print(tp_table)

    # ── 优势 / 薄弱点 / 亮点 / 担忧 ─────────────────────────────────────────
    # 用一个列表累积要展示的多行文本，最后统一拼接进面板。
    lines = []
    # 遍历四类分析项：每项给定（标题, 颜色, 报告字段名）。
    for label, color, key in [
        ("✅ 优势",     "green",   "strengths"),
        ("⚠️  薄弱点",  "red",     "weaknesses"),
        ("⭐ 亮点表现", "yellow",  "highlights"),
        ("🔍 关注点",   "magenta", "concerns"),
    ]:
        # 用 _ensure_list 把对应字段规整为字符串列表，防止字符串被逐字遍历。
        items = _ensure_list(report.get(key, []))
        # 仅当该类别有内容时才追加标题与条目。
        if items:
            # 追加带颜色的分类标题行。
            lines.append(f"[bold {color}]{label}：[/]")
            # 把每个条目格式化为带项目符号的列表项追加进去。
            lines += [f"  • {it}" for it in items]
            # 追加一个空行作为类别之间的视觉间隔。
            lines.append("")

    # 若累积到任何内容，则用黄色面板统一展示「详细分析」。
    if lines:
        console.print(Panel(
            "\n".join(lines),
            title="📋 详细分析",
            border_style="yellow",
            padding=(0, 2),
        ))


def _print_study_plan(study: dict) -> None:
    """
    打印复习计划。
    ★ 关键修复：practice_projects / mock_interview_tips 用 _ensure_list 保证是列表。
    """
    # 计划为空时无内容可展示，提前返回。
    if not study:
        return

    # 用于累积复习计划各行文本的缓冲列表，最后统一渲染进面板。
    lines   = []
    # 取出「总体建议」文本，缺失则为空字符串。
    overall = study.get("overall_advice", "")
    # 若有总体建议，作为开头一段先行展示。
    if overall:
        lines.append(f"[bold cyan]💡 总体建议：[/]{overall}\n")

    # 遍历按周拆分的学习计划列表。
    for w in study.get("weeks", []):
        # 防御性校验：非字典元素（脏数据）跳过，避免后续 .get 报错。
        if not isinstance(w, dict):
            continue
        # 取出本周学习目标与推荐资源（可能是字符串或列表）。
        goals     = w.get("goals", "")
        resources = w.get("resources", "")
        # goals / resources 在 StudyPlannerAgent 已规范为字符串，直接展示
        # 兜底处理：若仍为列表，则用中文分号拼接目标，便于单行展示。
        if isinstance(goals, list):
            goals = "；".join(goals)
        # 兜底处理：资源若为列表，用中文逗号拼接成单行。
        if isinstance(resources, list):
            resources = "，".join(resources)

        # 追加本周的标题行：周序号、主题，以及建议的每日学习时长。
        lines.append(
            f"[bold]📅 第 {w.get('week', '-')} 周：{w.get('theme', '-')}[/]"
            f"（每天 {w.get('daily_hours', '-')} 小时）"
        )
        # 有目标则追加一行目标说明。
        if goals:
            lines.append(f"  🎯 {goals}")
        # 有资源则追加一行资源说明。
        if resources:
            lines.append(f"  📖 {resources}")
        # 每周之间追加空行作为间隔。
        lines.append("")

    # ★ 用 _ensure_list 确保是列表，彻底防止逐字遍历
    # 规整「实战项目建议」为字符串列表。
    projects = _ensure_list(study.get("practice_projects", []))
    if projects:
        # 有项目建议时先追加分类标题。
        lines.append("[bold yellow]🔨 实战项目建议：[/]")
        # 逐条以项目符号形式追加。
        for p in projects:
            lines.append(f"  • {p}")
        # 追加空行作为与下一区块的间隔。
        lines.append("")

    # 规整「面试技巧提示」为字符串列表，同样防止逐字遍历。
    tips = _ensure_list(study.get("mock_interview_tips", []))
    if tips:
        # 有技巧提示时先追加分类标题。
        lines.append("[bold green]🎤 面试技巧提示：[/]")
        # 逐条以项目符号形式追加。
        for t in tips:
            lines.append(f"  • {t}")

    # 把所有累积的行拼接为多行文本，放进绿色面板统一展示。
    console.print(Panel(
        "\n".join(lines),
        title="📚 个性化复习计划",
        border_style="green",
        padding=(1, 2),
    ))


def _print_github_recommendations(recs: list) -> None:
    """
    打印 GitHub 学习资源推荐。
    ★ 修复：无论是否有结果都展示标题；无结果时展示友好提示。
    """
    # 推荐列表为空时无内容可展示，提前返回。
    if not recs:
        return

    # 打印推荐区块的总标题。
    console.print("\n[bold cyan]🔗 GitHub 学习资源推荐[/]")

    # 标志位：记录是否至少有一个薄弱点找到了仓库，用于决定最后是否给出兜底提示。
    any_result = False
    # 遍历每个「薄弱点 → 相关仓库」的推荐条目。
    for item in recs:
        # 取出该条针对的薄弱点描述。
        weakness = item.get("weakness", "")
        # 取出与该薄弱点匹配到的仓库列表。
        repos    = item.get("repos", [])

        # 先打印该薄弱点的小标题。
        console.print(f"\n  [bold yellow]📚 针对薄弱点：{weakness}[/]")

        # 该薄弱点未找到任何仓库：给出友好提示并跳过本条的表格渲染。
        if not repos:
            console.print("  [dim]（未找到相关仓库，建议手动搜索）[/dim]")
            continue

        # 走到这里说明至少有一条结果，置位标志。
        any_result = True
        # 构建展示仓库列表的表格（精简边框、暗色样式）。
        repo_table = Table(
            box=box.SIMPLE,
            show_header=True,
            header_style="bold",
            border_style="dim",
            padding=(0, 1),
        )
        # 添加四列：项目名、描述、Stars 数、主要语言。
        repo_table.add_column("项目",     style="cyan",         width=35)
        repo_table.add_column("描述",                           width=36)
        repo_table.add_column("⭐ Stars", justify="right",      width=10)
        repo_table.add_column("语言",     justify="center",     width=12)

        # 遍历该薄弱点下的每个仓库，逐行写入表格。
        for repo in repos:
            # 仓库名，缺失则用「-」占位。
            name = repo.get("name", "-")
            # 仓库主页 URL，用于给项目名加超链接；缺失则为空字符串。
            url  = repo.get("url",  "")
            # 仓库描述，截断到 36 字符以适配列宽；为空则用「-」占位。
            desc = (repo.get("description") or "-")[:36]
            # Star 数，缺失则默认 0。
            stars = repo.get("stars", 0)
            # 主要编程语言，为空则用「-」占位。
            lang  = repo.get("language") or "-"

            # 添加一行：有 URL 时把项目名渲染为可点击链接，否则展示纯文本；
            # Stars 用千分位格式化以便阅读。
            repo_table.add_row(
                f"[link={url}]{name}[/link]" if url else name,
                desc,
                f"{stars:,}",
                lang,
            )
        # 输出渲染好的仓库表格。
        console.print(repo_table)

    # 若遍历完所有条目都没有任何仓库结果，给出网络/限速相关的兜底提示。
    if not any_result:
        console.print(
            "\n  [dim]💡 GitHub API 可能因网络或限速无结果，"
            "建议配置 GITHUB_TOKEN 环境变量后重试[/dim]"
        )


@app.command()
def interview(
    # --jd：岗位 JD，必填（...），可传入文本本身或 .txt/.md 文件路径。
    jd: str = typer.Option(..., "--jd", help="岗位 JD 文本或文件路径"),
    # --resume：简历，可选；支持文本、.txt/.md 或 .pdf 文件路径。
    resume: str | None = typer.Option(None, "--resume", help="简历文本或文件路径"),
    # --total：本场面试出题数量，默认 5 题。
    total_questions: int = typer.Option(5, "--total", help="出题数量"),
):
    """启动一场交互式模拟面试"""
    # 初始化日志系统，确保后续各环节的日志按统一配置输出。
    setup_logger()
    # 延迟导入工作流编译入口：放在函数内可缩短 CLI 启动时间、避免循环依赖。
    from orchestration.graph import get_compiled_graph
    # 延迟导入全局会话记忆管理器，用于持久化保存每一步的会话状态。
    from memory.memory_manager import memory_manager
    # 导入 uuid 用于生成本场面试的唯一会话 ID。
    import uuid

    # 打印自适应宽度的欢迎面板作为程序开场。
    console.print(Panel.fit("[bold green]🎯 AI 模拟面试官[/]", border_style="green"))

    # ── 读取文件 ──────────────────────────────────────────────────────────────
    # 若 jd 传入的是 .txt/.md 文件路径，则读取文件内容替换为真正的 JD 文本。
    if jd.endswith((".txt", ".md")):
        jd = open(jd, encoding="utf-8").read()

    # 简历文本初始化为空字符串（未提供简历时保持为空）。
    resume_text = ""
    # 仅在用户提供了 --resume 时才处理简历。
    if resume:
        # 情况一：PDF 简历 —— 用 pypdf 逐页抽取文本后拼接。
        if resume.endswith(".pdf"):
            # 延迟导入 PDF 解析库，避免无 PDF 场景也强制依赖。
            from pypdf import PdfReader
            # 打开并解析 PDF 文件。
            reader = PdfReader(resume)
            # 逐页抽取文本（抽取失败的页用空字符串兜底）并用换行拼接为整篇文本。
            resume_text = "\n".join(page.extract_text() or "" for page in reader.pages)
        # 情况二：纯文本简历文件 —— 直接读取内容。
        elif resume.endswith((".txt", ".md")):
            resume_text = open(resume, encoding="utf-8").read()
        # 情况三：既非 PDF 也非文本文件路径 —— 视为直接传入的简历文本。
        else:
            resume_text = resume

    # 生成本场面试的唯一会话 ID（字符串形式的 UUID）。
    session_id = str(uuid.uuid4())
    # 获取已编译的工作流图对象，后续所有推理都通过它的 invoke 驱动。
    graph      = get_compiled_graph()

    # ── 阶段一：初始化 ────────────────────────────────────────────────────────
    # 构建初始会话状态字典，包含会话标识、JD/简历、面试控制开关及计数器等全部初值。
    init_state = {
        # 会话唯一标识。
        "session_id":            session_id,
        # 用户标识：CLI 场景固定为 cli_user。
        "user_id":               "cli_user",
        # 岗位 JD 文本。
        "jd_text":               jd,
        # 简历文本（可能为空）。
        "resume_text":           resume_text,
        # 当前意图：开始面试，驱动工作流进入出题流程。
        "intent":                "start_interview",
        # 触发开场的用户输入占位文本。
        "user_input":            "开始面试",
        # 当前难度等级，初始为中等。
        "current_difficulty":    "medium",
        # 当前题目索引，从 0 开始。
        "current_question_idx":  0,
        # 问答历史记录列表，初始为空。
        "qa_history":            [],
        # 评分记录列表，初始为空。
        "score_records":         [],
        # 是否正在等待用户作答的标志。
        "awaiting_answer":       False,
        # 是否正在等待对回答进行评估的标志。
        "awaiting_evaluation":   False,
        # 面试是否已结束的标志。
        "interview_finished":    False,
        # 是否需要对当前回答进行追问的标志。
        "should_followup":       False,
        # 已追问次数计数器。
        "followup_count":        0,
        # 单题最大追问次数上限。
        "max_followup":          2,
        # 是否强制结束面试的标志。
        "force_finish":          False,
        # 技能子状态（用于在多次技能调用间累积上下文），初始为空字典。
        "skill_state":           {},
        "total_questions":       total_questions,   # ★ 写入 state
    }

    # 提示用户正在分析输入并生成题目。
    console.print(f"[yellow]正在分析 JD 和简历，生成 {total_questions} 道题目...[/]")
    # 执行工作流的初始化阶段：解析 JD/简历、规划题目并生成第一题。
    state = graph.invoke(init_state)
    # 把初始化后的会话状态持久化保存，便于断点恢复或事后追溯。
    memory_manager.save_session(session_id, state)

    # 取出解析后的 JD 结构化信息（如岗位标题等）。
    jd_parsed     = state.get("jd_parsed", {})
    # 取出工作流规划出的题目列表。
    question_plan = state.get("question_plan", [])
    # 题目总数：以实际规划出的题目数量为准。
    total         = len(question_plan)

    # 打印岗位标题与本场题目总数概览。
    console.print(
        f"\n[bold]📋 岗位：[/]{jd_parsed.get('title', '-')}  "
        f"[bold]共 {total} 题[/]\n"
    )

    # 取出第一题题干文本。
    first_q = state.get("current_question_text", "")
    # 若第一题为空，说明题目生成失败，提示并直接结束本次面试。
    if not first_q:
        console.print("[red]题目生成失败，请检查日志[/]")
        return

    # 取出当前题目索引，用于显示「第 N 题」。
    cur_idx = state.get("current_question_idx", 0)
    # 打印第一题（题号从 1 开始，故索引 +1）。
    console.print(f"[bold blue]【第 {cur_idx + 1}/{total} 题】[/] {first_q}")
    # 打印技能使用提示。
    console.print(SKILL_HINT)

    # ── 阶段二：答题循环 ──────────────────────────────────────────────────────
    # 主循环：只要面试尚未结束，就持续向用户索取回答并推进流程。
    while not state.get("interview_finished", False):
        # 交互式获取用户对当前题目的回答。
        answer = Prompt.ask("\n[cyan]你的回答[/]")

        # 若回答（去空白、转小写后）命中结束关键词，则中断面试并退出函数。
        if answer.strip().lower() in FINISH_KEYWORDS:
            console.print("[yellow]面试中断，退出[/]")
            return

        # ── Skill 触发 ────────────────────────────────────────────────────────
        # 检测本次输入是否为技能命令（如 /quiz、/teach 等）。
        skill_result = _detect_skill(answer)
        # 命中技能：执行技能而不消耗当前题目的作答机会。
        if skill_result:
            # 解包技能名与技能参数。
            skill_name, skill_input = skill_result
            # 执行技能并更新状态（技能结果已在 _run_skill 内渲染）。
            state = _run_skill(graph, state, skill_name, skill_input)
            # 取回当前题目文本与索引，技能结束后重新提示用户继续作答。
            cur_q   = state.get("current_question_text", "")
            cur_idx = state.get("current_question_idx", 0)
            # 若仍有当前题目，则重新展示该题，提示用户继续作答。
            if cur_q:
                console.print(
                    f"\n[bold blue]【继续第 {cur_idx + 1}/{total} 题】[/] {cur_q}"
                )
            # 再次打印技能提示。
            console.print(SKILL_HINT)
            # 跳过本轮后续的「正常答题」逻辑，回到循环开头等待新的输入。
            continue

        # ── 正常答题 ──────────────────────────────────────────────────────────
        # 把用户回答写入状态的多个相关字段，供工作流评估使用。
        state["user_input"]          = answer
        # 记录最近一次用户回答（便于评估/追问引用）。
        state["last_user_answer"]    = answer
        # 将意图切换为「回答问题」，驱动工作流走评估分支。
        state["intent"]              = "answer_question"
        # 标记需要对本次回答进行评估。
        state["awaiting_evaluation"] = True
        # 标记不再处于「等待作答」状态（用户已作答）。
        state["awaiting_answer"]     = False

        # 执行工作流：评估回答、决定是否追问、生成下一题或结束面试。
        state = graph.invoke(state)
        # 每推进一步都持久化保存最新会话状态。
        memory_manager.save_session(session_id, state)

        # ── 面试结束 ──────────────────────────────────────────────────────────
        # 若工作流判定面试已结束，则展示面试官的结束寄语并跳出循环。
        if state.get("interview_finished", False):
            # 取出结束时的面试官致辞。
            farewell = state.get("agent_reply", "")
            # 有致辞内容则打印出来。
            if farewell:
                console.print(f"\n[bold red]💬 面试官：[/]{farewell}\n")
            # 跳出答题主循环，进入报告阶段。
            break

        # ── 追问 ──────────────────────────────────────────────────────────────
        # 若工作流决定对当前回答继续追问，则展示追问题并等待下一轮作答。
        if state.get("should_followup", False):
            # 取出追问问题文本。
            followup_q = state.get("current_question_text", "")
            # 有追问内容则打印。
            if followup_q:
                console.print(f"\n[bold red]🔍 面试官追问：[/]{followup_q}")
            # 打印技能提示。
            console.print(SKILL_HINT)
            # 回到循环开头继续等待用户对追问的回答。
            continue

        # ── 下一题 ────────────────────────────────────────────────────────────
        # 走到这里说明既未结束也不追问，应展示下一道题目。
        next_q   = state.get("current_question_text", "")
        # 取出下一题的索引。
        next_idx = state.get("current_question_idx", 0)
        # 有下一题则打印题号与题干。
        if next_q:
            console.print(
                f"\n[bold blue]【第 {next_idx + 1}/{total} 题】[/] {next_q}"
            )
        # 打印技能提示，进入下一轮作答。
        console.print(SKILL_HINT)

    # ── 阶段三：报告 ──────────────────────────────────────────────────────────
    # 打印一条分隔线，标志进入面试总结报告阶段。
    console.print("\n" + "─" * 60)
    # 渲染最终评估报告（总分、六维评分、主题表现、优劣势分析）。
    _print_report(state.get("final_report", {}))
    # 渲染个性化复习计划。
    _print_study_plan(state.get("study_plan", {}))
    # 渲染针对薄弱点的 GitHub 学习资源推荐。
    _print_github_recommendations(state.get("github_recommendations", []))


@app.command()
def build_index(kb_dir: str = typer.Option("rag/knowledge_base", "--kb")):
    """构建 RAG 索引"""
    # 延迟导入索引构建函数，避免无需该功能时也加载相关依赖。
    from rag.indexer import build_full_index
    # 初始化日志，便于观察索引构建过程。
    setup_logger()
    # 对指定知识库目录执行完整索引构建。
    build_full_index(kb_dir)


@app.command()
def check_env():
    """检查运行环境"""
    # 延迟导入环境检查函数。
    from scripts.check_env import check_all
    # 执行全部环境检查项（依赖、密钥、连通性等）。
    check_all()


@app.command()
def serve(
    # --host：Web 服务监听地址，默认 0.0.0.0（对外可访问）。
    host: str = typer.Option("0.0.0.0", "--host"),
    # --port：Web 服务监听端口，默认 8000。
    port: int = typer.Option(8000, "--port"),
):
    """启动 Web 服务"""
    # 导入 uvicorn 作为 ASGI 服务器来托管 FastAPI 应用。
    import uvicorn
    # 初始化日志配置。
    setup_logger()
    # 以模块路径方式启动 api.main:app；reload=False 表示生产模式不开启热重载。
    uvicorn.run("api.main:app", host=host, port=port, reload=False)


# 仅当本文件作为脚本直接运行时（而非被作为模块导入）才执行以下入口逻辑。
if __name__ == "__main__":
    # 调试用的打印语句，确认脚本入口被执行。
    print("111")
    # 启动 typer CLI 应用，解析命令行参数并分发到对应子命令。
    app()