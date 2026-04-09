import pymysql

def get_all_pedigree(conn):
    """
    获取全量系谱字典
    
    逻辑更新：
    如果是克隆猪，会自动向上追溯克隆链（A克隆自B，B克隆自C），
    直到找到非克隆的源头（C），然后使用 C 的父母作为 A 的遗传父母。
    这样 A 在计算近交系数时，就等价于 C。
    """
    cur = conn.cursor(pymysql.cursors.DictCursor)
    # 1. 查询时必须包含克隆相关字段
    cur.execute("SELECT id, father_id, mother_id, is_clone, clone_source_id FROM pigs")
    rows = cur.fetchall()
    
    # 2. 构建原始数据映射，方便通过 ID 快速查找任意猪的信息
    raw_map = {r["id"]: r for r in rows}
    
    pedigree = {}
    
    for row in rows:
        pig_id = row["id"]
        
        # 3. 寻找“有效父母”（处理克隆链）
        father_id = None
        mother_id = None
        
        current_pig = row
        visited_ids = set() # 用于防止克隆循环死锁 (例如 A克隆B, B克隆A)
        
        # 循环向上追溯：如果是克隆猪，就跳到它的供体
        while True:
            # 停止条件1：猪不存在，或进入死循环
            if not current_pig or current_pig['id'] in visited_ids:
                father_id, mother_id = None, None
                break
            
            visited_ids.add(current_pig['id'])
            
            # 判断是否为克隆且有来源
            if current_pig.get('is_clone') and current_pig.get('clone_source_id'):
                # 是克隆，跳转到供体，继续循环检查供体是否也是克隆
                donor_id = current_pig['clone_source_id']
                current_pig = raw_map.get(donor_id)
            else:
                # 不是克隆（或者已经追溯到最终的原始猪）
                # 【新增】检查数据有效性：防止父母是它自己（数据录入错误）
                pid = current_pig.get('father_id')
                mid = current_pig.get('mother_id')
                
                # 如果父亲等于自己，视为无效
                if pid == current_pig['id']: pid = None
                # 如果母亲等于自己，视为无效
                if mid == current_pig['id']: mid = None
                
                father_id = pid
                mother_id = mid
                break # 找到了，跳出循环
        
        # 将最终确定的遗传父母存入结果字典
        pedigree[pig_id] = (father_id, mother_id)
        
    return pedigree

def compute_inbreeding_A_matrix(pedigree):
    # 获取所有个体 ID 并排序，确保计算顺序一致
    animals = list(pedigree.keys())
    animals.sort() 
    
    # 建立索引映射：ID -> 索引 (0, 1, 2...)
    index = {a: i for i, a in enumerate(animals)}
    n = len(animals)

    # 2. 初始化 A 矩阵，全部置为 0
    A = [[0.0 for _ in range(n)] for _ in range(n)]

    # 3. 逐个计算
    for i, animal in enumerate(animals):
        # 这里取到的 father, mother 已经是被 get_all_pedigree 处理过的“遗传父母”
        father, mother = pedigree.get(animal, (None, None))

        f_idx = index.get(father)
        m_idx = index.get(mother)

        # 情况 A: 父母双全
        if f_idx is not None and m_idx is not None:
            # A[i][i] = 1 + 0.5 * A[father][mother]
            A[i][i] = 1 + 0.5 * A[f_idx][m_idx]

            # 计算该个体与之前个体的亲缘关系
            # A[i][j] = 0.5 * (A[father][j] + A[mother][j])
            for j in range(i):
                A[i][j] = 0.5 * (A[f_idx][j] + A[m_idx][j])
                A[j][i] = A[i][j] # 矩阵是对称的，补全另一边
        
        # 情况 B: 父母不全（只有一个，或者都没有）
        else:
            # 【修改点】更严谨的计算逻辑
            # 即使父母不全，也需要计算个体与已知那一半血统的关系
            # 如果完全未知（父母都没有），A[i][i] 保持为 0.0 (因为是初始化过的)，最后 F = -1 ?
            # 不对，完全未知的基础群体，与自己关系应为 1。所以这里默认设为 1。
            
            A[i][i] = 1.0 
            
            # 尝试利用已知的父亲或母亲计算关系
            # 即使只有一个父母，这头猪也与该父母有 0.5 的亲缘关系
            known_parent_idx = f_idx if f_idx is not None else m_idx
            
            if known_parent_idx is not None:
                for j in range(i):
                    # 如果只有父亲：A[i][j] = 0.5 * A[father][j]
                    # 如果只有母亲：A[i][j] = 0.5 * A[mother][j]
                    A[i][j] = 0.5 * A[known_parent_idx][j]
                    A[j][i] = A[i][j]

    # 4. 提取近交系数
    F_dict = {}
    for animal, i in index.items():
        # 近交系数 = 个体与自己的亲缘关系 - 1
        F_dict[animal] = A[i][i] - 1

    return F_dict
