import pymysql

def get_all_pedigree(conn):

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
        

        while True:
            # 停止条件1：猪不存在，或进入死循环
            if not current_pig or current_pig['id'] in visited_ids:
                father_id, mother_id = None, None
                break
            
            visited_ids.add(current_pig['id'])
            
            if current_pig.get('is_clone') and current_pig.get('clone_source_id'):
                donor_id = current_pig['clone_source_id']
                current_pig = raw_map.get(donor_id)
            else:

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

        father, mother = pedigree.get(animal, (None, None))

        f_idx = index.get(father)
        m_idx = index.get(mother)

        # 情况 A: 父母双全
        if f_idx is not None and m_idx is not None:

            A[i][i] = 1 + 0.5 * A[f_idx][m_idx]


            for j in range(i):
                A[i][j] = 0.5 * (A[f_idx][j] + A[m_idx][j])
                A[j][i] = A[i][j] # 矩阵是对称的，补全另一边
        

        else:

            
            A[i][i] = 1.0 
            

            known_parent_idx = f_idx if f_idx is not None else m_idx
            
            if known_parent_idx is not None:
                for j in range(i):

                    A[i][j] = 0.5 * A[known_parent_idx][j]
                    A[j][i] = A[i][j]

    # 4. 提取近交系数
    F_dict = {}
    for animal, i in index.items():

        F_dict[animal] = A[i][i] - 1

    return F_dict
