
"""
调试 Weaviate 数据库：
- 查看所有 collections
- 查看 schema
- 查看数据量
- 展示几条样例数据
"""

# 从向量检索模块导入获取 Weaviate 客户端的工厂函数，统一在此处获取连接配置
from rag.retrievers.vector_retriever import get_weaviate_client


# 主流程：连接 Weaviate，遍历所有 collection 并打印每个 collection 的样例数据
def main():
    # 获取（并建立）一个 Weaviate 客户端连接
    client = get_weaviate_client()

    # 使用 try/finally 确保无论中途是否出错，最终都会关闭客户端连接，避免连接泄漏
    try:
        # 打印分隔线和标题，使输出更易读
        print("=" * 80)
        print("📦 Weaviate Collections")
        print("=" * 80)

        # 列出数据库中所有 collection（返回的是 collection 名称到配置的映射）
        collections = client.collections.list_all()

        # 若没有任何 collection，提示并提前结束（finally 仍会执行关闭连接）
        if not collections:
            print("❌ 当前没有任何 collection")
            return

        # 遍历每一个 collection 名称，逐个展示其内容
        for name in collections:
            # 打印当前正在查看的 collection 名称
            print(f"\n🧠 Collection: {name}")

            # 根据名称获取对应的 collection 操作对象，用于后续查询
            col = client.collections.get(name)

            # -----------------------------
            # 查看数据
            # -----------------------------
            # 打印样例数据小标题
            print("\n📄 Sample Objects:\n")

            # 单独 try：某个 collection 查询失败不应中断对其他 collection 的遍历
            try:
                # 从该 collection 中抓取最多 5 条对象作为样例
                result = col.query.fetch_objects(limit=5)

                # 取出查询结果中的对象列表
                objs = result.objects

                # 若该 collection 没有数据，提示并跳过当前循环，继续看下一个 collection
                if not objs:
                    print("⚠️ 当前 collection 没有数据")
                    continue

                # 打印实际查询到的样例数量
                print(f"✅ 查询到 {len(objs)} 条样例数据\n")

                # 枚举每条样例对象，idx 从 1 开始用于人类可读的编号
                for idx, obj in enumerate(objs, start=1):
                    # 打印分隔线和当前对象编号
                    print("-" * 80)
                    print(f"#{idx}")
                    # 打印对象的唯一标识 UUID
                    print(f"UUID: {obj.uuid}")

                    # 取出对象的属性字典；若为 None 则用空字典兜底，避免后续遍历报错
                    props = obj.properties or {}

                    # 遍历该对象的每个属性键值对
                    for k, v in props.items():
                        # 对过长的字符串属性进行截断，避免控制台输出过于冗长
                        if isinstance(v, str) and len(v) > 200:
                            # 仅保留前 200 个字符并追加省略号
                            v = v[:200] + "..."

                        # 打印属性名与（可能已截断的）属性值
                        print(f"{k}: {v}")

                    # 每条对象之间额外空行，提升可读性
                    print()

            # 捕获该 collection 查询过程中的任意异常并打印，保证整体流程继续
            except Exception as e:
                print(f"❌ 查询失败: {e}")

    # 无论是否发生异常，最终都会执行：关闭客户端连接
    finally:
        # 关闭 Weaviate 客户端，释放底层连接资源
        client.close()
        # 打印关闭成功提示
        print("\n🔒 Weaviate client 已关闭")


# 当脚本被直接运行时执行主流程
if __name__ == "__main__":
    # 调用主函数开始调试输出
    main()

    # python -m tests.show_weaviate