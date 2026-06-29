"""
GitHub 仓库分析工具：
- 搜索学习某技术主题的优质开源项目
- 分析指定仓库的 star / README / 技术栈
"""
# 启用延迟注解求值，避免前向引用问题并简化类型注解书写。
from __future__ import annotations

# 标准库 time：用于计算限速等待时间（结合时间戳做差值）。
import time
# 类型注解工具：标注返回值与参数的容器/可选类型。
from typing import Any, Dict, List, Optional

# httpx：现代化的同步/异步 HTTP 客户端，这里用其同步 Client 访问 GitHub API。
import httpx
# loguru 的 logger：统一日志输出。
from loguru import logger

# 从项目配置模块导入全局 settings，用于读取 GitHub Token 等配置。
from config import settings

# GitHub 仓库搜索 REST API 端点。
SEARCH_URL = "https://api.github.com/search/repositories"

# 语言列表（分开查询，避免 OR 语法被 GitHub API 截断）
# 预留的常见编程语言集合，便于后续按语言维度扩展查询。
_LANGUAGES = ["python", "javascript", "typescript", "java", "go"]


def _build_headers() -> Dict[str, str]:
    """构造 GitHub API 请求头。

    返回:
        含 Accept 头的字典；若配置了 Token 则附带 Bearer 认证头。
    """
    # 指定接受 GitHub v3 JSON 媒体类型，确保返回标准 JSON 结构。
    headers = {"Accept": "application/vnd.github+json"}
    # 若配置中存在 GitHub Token，则使用带认证的请求以提高限速额度。
    if settings.github_token:
        # 以 Bearer 方案携带 Token 进行认证。
        headers["Authorization"] = f"Bearer {settings.github_token}"
        logger.debug("GitHub API 使用认证 Token")
    else:
        # 未配置 Token 时为匿名访问，GitHub 对匿名请求限速更严（约 60 次/小时）。
        logger.debug("GitHub API 未配置 Token，使用匿名访问（限速60次/小时）")
    # 返回构造好的请求头，供后续 HTTP 请求复用。
    return headers


def _clean_topic(topic: str) -> str:
    """清洗搜索主题：去除中文标点、截断过长文本

    参数:
        topic: 原始主题文本（可能含中文标点、过多词语）。
    返回:
        归一化后的英文/数字关键词串；若清洗后为空则回退为 "machine learning"。
    """
    # 局部导入正则模块，仅在需要清洗时加载。
    import re
    # 只保留字母、数字、空格、连字符
    # 将除单词字符、空白、连字符外的所有字符（含中文标点）替换为空格；UNICODE 标志确保正确识别。
    cleaned = re.sub(r"[^\w\s\-]", " ", topic, flags=re.UNICODE)
    # 截断到前3个词，避免 query 过长
    # 按空白拆分并最多取前 4 个词，控制查询串长度（注释说前3，实际取4个）。
    words = cleaned.split()[:4]
    # 用空格拼接关键词并去除首尾空白；若结果为空则回退默认主题，保证查询始终有效。
    return " ".join(words).strip() or "machine learning"


def search_learning_repos(
    topic: str,
    max_results: int = 3,
    min_stars: int = 100,
) -> List[Dict[str, Any]]:
    """
    搜索与 topic 相关的优质学习仓库。
    策略：先用精确 topic 搜索，不足时用清洗后的关键词补充。

    参数:
        topic: 待搜索的技术主题。
        max_results: 最多返回的仓库数量，默认 3。
        min_stars: star 数门槛，过滤低质量仓库，默认 100。
    返回:
        仓库信息字典列表（名称、URL、stars、描述、语言、更新时间）。
    """
    # 构造带认证（或匿名）的请求头。
    headers = _build_headers()
    # 对原始主题做清洗，得到适合 GitHub 查询的关键词串。
    clean   = _clean_topic(topic)

    # 清洗后若为空（理论上已有默认回退，这里再做一次防御），跳过搜索。
    if not clean:
        logger.warning("搜索主题清洗后为空，跳过：{}", topic)
        return []

    # ★ 简化 query：不用 OR 语法，只搜索 topic + stars 门槛
    # 拼接 GitHub 搜索语法：关键词 + stars 数大于门槛，避免复杂 OR 语法导致截断。
    query = f"{clean} stars:>{min_stars}"

    # 组装查询参数。
    params = {
        "q":        query,                       # 查询语句
        "sort":     "stars",                     # 按 star 数排序
        "order":    "desc",                      # 降序，优先返回高星仓库
        "per_page": max(max_results * 2, 10),   # 多取一些，过滤后取前 N
    }

    # 记录实际发出的查询，便于排障。
    logger.info("GitHub 搜索：query={}", query)

    # 发起请求并处理各类异常；任一异常均降级为返回空列表，保证调用方不中断。
    try:
        # 创建带 15 秒超时、自动跟随重定向的同步 HTTP 客户端。
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            # 发起 GET 搜索请求。
            resp = client.get(SEARCH_URL, headers=headers, params=params)

            # 处理限速
            # HTTP 403 通常表示触发 GitHub 限速。
            if resp.status_code == 403:
                # 从响应头读取限速重置的 Unix 时间戳（无则按 0）。
                reset_ts = int(resp.headers.get("X-RateLimit-Reset", 0))
                # 计算还需等待的秒数（不为负），仅用于日志提示。
                wait     = max(reset_ts - int(time.time()), 0)
                logger.warning("GitHub API 限速，需等待 {} 秒", wait)
                # 被限速时直接返回空结果，不阻塞主流程。
                return []

            # 处理认证失败
            # HTTP 401 表示 Token 无效，尝试去掉认证头改为匿名重试一次。
            if resp.status_code == 401:
                logger.warning("GitHub Token 无效，尝试匿名请求")
                # 移除认证头（若不存在则忽略）。
                headers.pop("Authorization", None)
                # 以匿名方式重新发起同一查询。
                resp = client.get(SEARCH_URL, headers=headers, params=params)

            # 对其余非 2xx 状态码抛出异常，交由下方 except 统一处理。
            resp.raise_for_status()
            # 解析响应体为 JSON 字典。
            data = resp.json()

    except httpx.TimeoutException:
        # 请求超时：记录并返回空列表。
        logger.warning("GitHub 搜索超时：{}", topic)
        return []
    except httpx.HTTPStatusError as e:
        # 非 2xx 的 HTTP 状态错误：记录并返回空列表。
        logger.warning("GitHub HTTP 错误：{} → {}", topic, e)
        return []
    except Exception as e:
        # 兜底捕获其他未预期异常（网络、解析等），保证函数不抛出。
        logger.warning("GitHub 搜索失败：{} → {}", topic, e)
        return []

    # 从结果中取出仓库条目列表（无则为空列表）。
    items   = data.get("items", [])
    # 用于收集最终返回的、经筛选的仓库信息。
    results = []

    # 遍历搜索到的每个仓库条目，逐条整理为精简结构。
    for item in items:
        # 已凑够 max_results 个结果则停止，避免多余处理。
        if len(results) >= max_results:
            break
        # 过滤明显不相关（名字完全不含关键词的）
        # 取仓库全名并转小写（预留用于关键词相关性判断）。
        name = (item.get("full_name") or "").lower()
        # 取仓库描述并转小写（预留用于关键词相关性判断）。
        desc = (item.get("description") or "").lower()
        # 提取清洗后关键词的首个词（预留作为相关性匹配依据）。
        kw   = clean.lower().split()[0] if clean else ""

        # 将该仓库的关键信息整理为标准化字典并加入结果列表。
        results.append({
            "name":        item.get("full_name", "-"),              # 仓库全名 owner/repo
            "url":         item.get("html_url", ""),                # 仓库网页地址
            "stars":       item.get("stargazers_count", 0),         # star 数量
            "description": (item.get("description") or "")[:200],   # 描述，截断到 200 字符
            "language":    item.get("language") or "-",             # 主要编程语言
            "updated_at":  item.get("updated_at", ""),              # 最近更新时间
        })

    # 记录本次搜索的命中数量，便于观测效果。
    logger.info(
        "GitHub 搜索完成：topic={}, 找到 {} 个仓库", topic, len(results)
    )
    # 返回整理后的仓库信息列表。
    return results


def analyze_repo(owner: str, repo: str) -> Dict[str, Any]:
    """分析指定仓库的基本信息

    参数:
        owner: 仓库所属的用户名或组织名。
        repo: 仓库名称。
    返回:
        仓库基本信息字典（名称、stars、forks、语言、描述、URL、topics、更新时间）；
        请求失败时返回空字典。
    """
    # 构造请求头（带认证或匿名）。
    headers = _build_headers()
    # 拼接获取单个仓库详情的 API 地址。
    url     = f"https://api.github.com/repos/{owner}/{repo}"
    # 请求并解析；任何异常均降级为返回空字典。
    try:
        # 创建带 15 秒超时的同步 HTTP 客户端。
        with httpx.Client(timeout=15) as client:
            # 发起 GET 请求获取仓库详情。
            resp = client.get(url, headers=headers)
            # 非 2xx 状态码抛出异常，交由下方 except 处理。
            resp.raise_for_status()
            # 解析响应为 JSON 字典。
            data = resp.json()
            # 提取并返回仓库的关键字段，统一为精简结构。
            return {
                "name":        data.get("full_name"),                 # 仓库全名
                "stars":       data.get("stargazers_count", 0),       # star 数量
                "forks":       data.get("forks_count", 0),            # fork 数量
                "language":    data.get("language"),                  # 主要编程语言
                "description": (data.get("description") or "")[:300], # 描述，截断到 300 字符
                "url":         data.get("html_url"),                  # 仓库网页地址
                "topics":      data.get("topics", []),                # 主题标签列表
                "updated_at":  data.get("updated_at"),                # 最近更新时间
            }
    except Exception as e:
        # 捕获所有异常（网络/状态/解析等），记录后返回空字典，保证调用方健壮。
        logger.warning("GitHub 仓库分析失败 {}/{}: {}", owner, repo, e)
        return {}