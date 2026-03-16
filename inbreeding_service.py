# services/inbreeding_service.py

# services/inbreeding_service.py

def get_all_pedigree(conn):
    """
    获取全量系谱字典 (仅包含在册猪)
    """
    cur = conn.cursor()
    cur.execute("SELECT id, father_id, mother_id FROM pigs WHERE status=1")
    rows = cur.fetchall()
    return {r["id"]: (r["father_id"], r["mother_id"]) for r in rows}

def compute_inbreeding_A_matrix(pedigree):
    """
    使用 A矩阵 (Tabular Method) 计算所有个体的近交系数
    
    F_x = A_xx - 1
    
    优点：
    1. 不会漏算祖先自身的近交系数 (如果父母近交，A_xy 会自动变大，进而影响 F)。
    2. 不需要复杂的路径搜索逻辑，算法更稳健。
    """
    # 1. 获取所有个体 ID 并排序
    # ⚠️ 关键：必须排序，确保父母（ID小）排在子女（ID大）前面
    # 因为计算公式 A[i][j] 依赖 A[father][j] 和 A[mother][j]
    # 如果 i 是子女，但 father 的索引 i_f > i，那么 A[father][j] 可能还没算出来，导致结果为0。
    animals = list(pedigree.keys())
    animals.sort() 
    
    # 建立索引映射：ID -> 索引 (0, 1, 2...)
    index = {a: i for i, a in enumerate(animals)}
    n = len(animals)

    # 2. 初始化 A 矩阵，全部置为 0
    A = [[0.0 for _ in range(n)] for _ in range(n)]

    # 3. 逐个计算
    for i, animal in enumerate(animals):
        father, mother = pedigree.get(animal, (None, None))

        # 基础个体（无父母）：与自己亲缘关系为 1
        if father is None or mother is None:
            A[i][i] = 1.0
        else:
            f = index[father]
            m = index[mother]

            # 对角线：A_ii = 1 + 0.5 * A_fm
            # 这里用到了父亲和母亲之间的亲缘关系 A_fm
            # 如果父母近交，A_fm > 0.5，那么子女 A_ii 就会 > 1，F > 0
            A[i][i] = 1 + 0.5 * A[f][m]


            # 非对角线：A_ij = 0.5 * (A_fj + A_mj)
            # 计算该个体与其他个体的亲缘关系
            for j in range(i):
                A[i][j] = 0.5 * (A[f][j] + A[m][j])
                A[j][i] = A[i][j] # 矩阵是对称的，补全另一边

    # 4. 提取近交系数
    F_dict = {}
    for animal, i in index.items():
        # 近交系数 = 个体与自己的亲缘关系 - 1
        # A[i][i] 实际上包含了 (1 + F_x)，所以减去 1 就是 F_x
        F_dict[animal] = A[i][i] - 1

    return F_dict