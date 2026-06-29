"""
动态难度状态机：
连续答对 -> 自动升难度；连续答错 -> 自动降难度
三级：easy / medium / hard
"""
# 启用未来注解特性，使类型注解延迟求值，避免前向引用问题
from __future__ import annotations

# 导入类型构造器：Any 表示任意类型，Dict 表示字典泛型
from typing import Any, Dict

# 导入 loguru 日志器，用于记录难度升降事件
from loguru import logger

# 导入全局配置对象，从中读取难度档位与升降阈值等参数
from config import settings

# 难度档位列表（按由易到难顺序排列），如 ["easy", "medium", "hard"]
LEVELS = settings.difficulty_levels
# 构建「难度名 -> 序号」的映射，便于通过索引进行升/降档计算
# 例如 {"easy": 0, "medium": 1, "hard": 2}
ORDER = {lv: i for i, lv in enumerate(LEVELS)}


def update_difficulty(state: Dict[str, Any]) -> None:
    """
    在每次单题评估后调用，根据 is_correct 更新难度。
    规则：
      - 连续答对 >= N 次 -> 升一档
      - 连续答错 >= N 次 -> 降一档
      - 否则保持
    """
    # 读取上一题的判定结果（是否答对），缺省视为答错（False）
    is_correct = state.get("last_correctness", False)
    # 读取当前难度档位，缺省为 medium（中等）
    current = state.get("current_difficulty", "medium")
    # 读取当前连续答对次数，缺省为 0
    cons_correct = state.get("consecutive_correct", 0)
    # 读取当前连续答错次数，缺省为 0
    cons_wrong = state.get("consecutive_wrong", 0)

    # 根据本题对错更新连续计数：答对则累加答对计数并清零答错计数，
    # 答错则相反——这样可保证「连续」语义（一旦中断即归零）
    if is_correct:
        cons_correct += 1
        cons_wrong = 0
    else:
        cons_wrong += 1
        cons_correct = 0

    # 先假定难度不变，后续按条件覆盖
    new_level = current
    # 取当前难度对应的序号；若难度名异常则默认按 1（medium）处理
    idx = ORDER.get(current, 1)

    # 若连续答对达到升档阈值，且当前不是最高档（idx 未到最后一档），则升一档
    if cons_correct >= settings.consecutive_correct_to_upgrade and idx < len(LEVELS) - 1:
        # 取更高一档的难度名
        new_level = LEVELS[idx + 1]
        # 升档后清零连续答对计数，避免一次性连跳多档
        cons_correct = 0
        # 记录难度上升日志
        logger.info("📈 难度上升：{} -> {}", current, new_level)
    # 否则若连续答错达到降档阈值，且当前不是最低档（idx 大于 0），则降一档
    elif cons_wrong >= settings.consecutive_wrong_to_downgrade and idx > 0:
        # 取更低一档的难度名
        new_level = LEVELS[idx - 1]
        # 降档后清零连续答错计数，避免一次性连降多档
        cons_wrong = 0
        # 记录难度下降日志
        logger.info("📉 难度下降：{} -> {}", current, new_level)

    # 将更新后的难度与连续计数写回状态，供后续出题/评估节点使用
    state["current_difficulty"] = new_level
    state["consecutive_correct"] = cons_correct
    state["consecutive_wrong"] = cons_wrong
