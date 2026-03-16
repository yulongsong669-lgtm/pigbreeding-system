from flask import Flask, render_template, request, redirect, jsonify, session
from database import get_db, init_db
from services.inbreeding_service import get_all_pedigree, compute_inbreeding_A_matrix
import csv
import io
import pymysql
from datetime import datetime


app = Flask(__name__)
app.secret_key = 'clonorgan_pigfarm'

# 初始化数据库
init_db()

# --------------------
# 路由定义
# --------------------

@app.route("/")
def index():
    # 获取 URL 参数 ?status=2
    status_filter = request.args.get('status', '1')
    
    with get_db() as conn:
        cur = conn.cursor()
        
        # 1. 查询猪只列表 (根据状态筛选)
        sql = "SELECT * FROM pigs WHERE 1=1"
        params = []
        
        if status_filter:
            sql += " AND status=%s"
            params.append(status_filter)
            
        sql += " ORDER BY id DESC"
        
        cur.execute(sql, tuple(params))
        pigs = cur.fetchall()
        
        #  修复：查询所有不重复的品种 (前端筛选框需要)
        cur.execute("SELECT DISTINCT breed FROM pigs WHERE breed IS NOT NULL AND breed != '' ORDER BY breed")
        breeds = [row["breed"] for row in cur.fetchall()]
        
        #  修复：查询所有厂区 (前端筛选框需要)
        cur.execute("SELECT * FROM farms")
        farms = cur.fetchall()

    return render_template("index.html", pigs=pigs, breeds=breeds, farms=farms)


@app.route("/pig/<int:pig_id>")
def pig(pig_id):
    with get_db() as conn:
        cur = conn.cursor()
        
        # 1. 获取猪只基本信息
        cur.execute("SELECT * FROM pigs WHERE id=%s", (pig_id,))
        pig = cur.fetchone()
        
        # 2. 获取厂区名称 (保持不变)
        farm_name = "未知"
        if pig and pig.get("farm_id"):
            cur.execute("SELECT name FROM farms WHERE id=%s", (pig["farm_id"],))
            farm_row = cur.fetchone()
            if farm_row:
                farm_name = farm_row["name"]

        # 3. 使用 A矩阵法重新计算
        # 获取全量系谱
        pedigree = get_all_pedigree(conn)
        
        # 计算全群 F 值
        all_F = compute_inbreeding_A_matrix(pedigree)
        
        # 提取当前猪的 F 值
        current_F = all_F.get(pig_id, 0.0)
        print(f"[A-Matrix] Pig {pig_id}: F = {current_F}")
        
        # 强制更新显示值（使用计算出的新值，而不是数据库里的旧值）
        pig['inbreeding'] = current_F

        # 4. 其他数据查询 (保持不变)
        cur.execute("SELECT * FROM phenotype WHERE pig_id=%s", (pig_id,))
        phenotypes = cur.fetchall()
        cur.execute("SELECT * FROM genotype WHERE pig_id=%s", (pig_id,))
        genotypes = cur.fetchall()
        cur.execute("SELECT * FROM vaccinations WHERE pig_id=%s ORDER BY vacc_date ASC", (pig_id,))
        vaccinations = cur.fetchall()
    
    return render_template("pig.html", pig=pig, phenotypes=phenotypes, genotypes=genotypes, vaccinations=vaccinations, farm_name=farm_name)

@app.route("/add_pig", methods=["GET", "POST"])
def add_pig():
    # GET 请求：获取下拉列表数据
    current_farm_id = session.get('current_farm_id', 1)

    with get_db() as conn:
        cur = conn.cursor()
        
        # 查询公猪和母猪列表 (只在册的)
        cur.execute("SELECT id, ear_tag FROM pigs WHERE farm_id=%s AND sex = 'M'", (current_farm_id,))
        boars = cur.fetchall()
        cur.execute("SELECT id, ear_tag FROM pigs WHERE farm_id=%s AND sex = 'F'", (current_farm_id,))
        sows = cur.fetchall()

        # 查询所有厂区
        cur.execute("SELECT id, name FROM farms")
        farms = cur.fetchall()

    if request.method == "POST":
        data = request.form
        ear_tag = data.get("ear_tag")
        sex = data.get("sex")
        breed = data.get("breed")
        birth_date = data.get("birth_date")
        father_id = data.get("father_id") or None
        mother_id = data.get("mother_id") or None
        farm_id = data.get("farm_id") or current_farm_id

        with get_db() as conn:
            cursor = conn.cursor()
            # 1. 插入猪只
            cursor.execute("""
                INSERT INTO pigs (ear_tag, sex, breed, birth_date, father_id, mother_id, farm_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (ear_tag, sex, breed, birth_date, father_id, mother_id, farm_id))
            pig_id = cursor.lastrowid

            # 2. 插入疫苗记录
            vaccine_name = request.form.getlist("vaccine_name")
            vacc_dates = request.form.getlist("vacc_date")
            notes = request.form.getlist("vacc_notes")
            for name, date, note in zip(vaccine_name, vacc_dates, notes):
                if name and date:
                    cursor.execute("""
                        INSERT INTO vaccinations (pig_id, vaccine, vacc_date, notes)
                        VALUES (%s, %s, %s, %s)
                    """, (pig_id, name, date, note))

            # 3. ✅ [修改] 使用 A 矩阵法更新全群近交系数
            # 这样能确保新猪（以及受影响的父母）的系数是准确的
            pedigree = get_all_pedigree(conn)
            all_F = compute_inbreeding_A_matrix(pedigree)
            
            # 批量更新数据库里的 inbreeding 字段
            for pid, f_val in all_F.items():
                cursor.execute("UPDATE pigs SET inbreeding=%s WHERE id=%s", (f_val, pid))
            
            conn.commit() # 提交所有更改

        return redirect("/")

    return render_template("add_pig.html", boars=boars, sows=sows, farms=farms)

@app.route("/get_parents/<int:farm_id>")
def get_parents(farm_id):
    """根据厂区ID获取公猪和母猪列表，供AJAX调用"""
    with get_db() as conn:
        cur = conn.cursor()
        # 查询该厂区的公猪
        cur.execute("SELECT id, ear_tag FROM pigs WHERE farm_id=%s AND sex='M' AND status=1", (farm_id,))
        boars = cur.fetchall()
        # 查询该厂区的母猪
        cur.execute("SELECT id, ear_tag FROM pigs WHERE farm_id=%s AND sex='F' AND status=1", (farm_id,))
        sows = cur.fetchall()
        
        return jsonify({"boars": boars, "sows": sows})

@app.route("/delete_pig/<int:pig_id>", methods=["POST"])
def delete_pig(pig_id):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM vaccinations WHERE pig_id=%s", (pig_id,))
        cursor.execute("DELETE FROM phenotype WHERE pig_id=%s", (pig_id,))
        cursor.execute("DELETE FROM genotype WHERE pig_id=%s", (pig_id,))
        cursor.execute("DELETE FROM pigs WHERE id=%s", (pig_id,))
    return redirect("/")

# 淘汰路由 
@app.route("/eliminate_pig/<int:pig_id>", methods=["POST"])
def eliminate_pig(pig_id):
    """将猪只状态改为：淘汰"""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE pigs SET status=2 WHERE id=%s", (pig_id,))
    return redirect("/")

#  使用路由 
@app.route("/use_pig/<int:pig_id>", methods=["POST"])
def use_pig(pig_id):
    """将猪只状态改为：使用"""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE pigs SET status=3 WHERE id=%s", (pig_id,))
    return redirect("/")
@app.route("/vaccines/<int:pig_id>")
def vaccines(pig_id):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT vaccine, vacc_date FROM vaccinations WHERE pig_id=%s ORDER BY vacc_date", (pig_id,))
        data = cur.fetchall()

    result = [{"vaccine": r["vaccine"], "vacc_date": r["vacc_date"]} for r in data]
    return jsonify(result)

@app.route("/group/<gid>")
def group(gid):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM pigs WHERE group_id=%s", (gid,))
        pigs = cur.fetchall()
    return render_template("group.html", pigs=pigs)

@app.route("/import", methods=["GET", "POST"])
def import_pigs():
    if request.method == "POST":
        file = request.files["file"]
        
        # 1. 读取文件内容
        file_content = file.stream.read()

        # 2. 尝试解码
        try:
            stream = io.StringIO(file_content.decode("UTF8"))
        except UnicodeDecodeError:
            try:
                stream = io.StringIO(file_content.decode("GBK"))
            except Exception as e:
                return f"文件编码错误: {e}"
            
        # --- 智能检测分隔符 ---
        first_line = stream.readline()
        detected_delimiter = ','
        if ';' in first_line:
            detected_delimiter = ';'
        elif '\t' in first_line:
            detected_delimiter = '\t'
        
        print(f"🔍 检测到分隔符: ['{detected_delimiter}']")
        stream.seek(0)
        reader = csv.DictReader(stream, delimiter=detected_delimiter)

        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, name FROM farms")
            farms = cur.fetchall()
            farm_map = {row["name"]: row["id"] for row in farms}
            
            # 获取当前用户在网页上选中的厂区，作为默认值
            current_farm_id = session.get('current_farm_id', 1)

            # 构建现有猪的映射（全厂区查找，避免跨厂区重名耳号问题）
            cur.execute("SELECT id, ear_tag FROM pigs")
            existing_pigs = cur.fetchall()
            pig_map = {row["ear_tag"]: row["id"] for row in existing_pigs}

            import_batch = []
            error_logs = []

            # --- 第一步：插入新猪 ---
            for row in reader:
                ear_tag = row.get("ear_tag")
                sex = row.get("sex")
                breed = row.get("breed")
                birth_date = row.get("birth_date")
                
                ear_tag = str(ear_tag).strip() if ear_tag is not None else ""
                sex = str(sex).strip() if sex is not None else ""
                breed = str(breed).strip() if breed is not None else ""
                birth_date = str(birth_date).strip() if birth_date is not None else ""

                if not ear_tag:
                    continue

                # 
                farm_name_str = row.get("farm_name", "").strip()
                if farm_name_str and farm_name_str in farm_map:
                    target_farm_id = farm_map[farm_name_str]
                else:
                    # 如果CSV没填，就用当前网页选中的厂区
                    target_farm_id = current_farm_id

                try:
                    # 
                    cur.execute(
                        "INSERT INTO pigs (ear_tag, sex, breed, birth_date, father_id, mother_id, farm_id) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                        (ear_tag, sex, breed, birth_date, None, None, target_farm_id)
                    )
                    
                    new_id = cur.lastrowid
                    pig_map[ear_tag] = new_id

                    # 
                    import_batch.append({
                        "id": new_id,
                        "farm_id": target_farm_id,
                        "father_tag": str(row.get("father_tag")).strip() if row.get("father_tag") else "",
                        "mother_tag": str(row.get("mother_tag")).strip() if row.get("mother_tag") else ""
                    })
                
                except pymysql.IntegrityError:
                    error_logs.append(f"耳号 {ear_tag} 已存在，跳过。")
                except Exception as e:
                    error_logs.append(f"行 {ear_tag} 导入失败: {e}")

            conn.commit()

            # --- 第二步：更新父母关系 ---
            update_count = 0
            for item in import_batch:
                father_id = pig_map.get(item["father_tag"])
                mother_id = pig_map.get(item["mother_tag"])

                if father_id is not None or mother_id is not None:
                    cur.execute(
                        "UPDATE pigs SET father_id=%s, mother_id=%s WHERE id=%s",
                        (father_id, mother_id, item["id"])
                    )
                    update_count += 1
            
            conn.commit()

            # --- 第三步：批量计算近交系数 ---
            print("========== 开始计算近交系数 ==========")
            print(f"待计算数量: {len(import_batch)}")
            
            calc_count = 0
            for item in import_batch:
                try:
                    
                    pedigree = get_all_pedigree(conn)
                    
                    F_new = compute_inbreeding_A_matrix(pedigree, item["id"])
                    cur.execute("UPDATE pigs SET inbreeding=%s WHERE id=%s", (F_new, item["id"]))
                    calc_count += 1
                except Exception as e:
                    print(f"计算 ID {item['id']} 失败: {e}")
            
            conn.commit()
            print(f"计算完成，成功更新 {calc_count} 条记录")
            print("=======================================")

        return redirect(f"/?imported={len(import_batch)}&linked={update_count}&calc={calc_count}")

    return render_template("import.html")

@app.route("/pedigree/<int:pig_id>")
def pedigree(pig_id):
    with get_db() as conn:
        cur = conn.cursor()

        def build_tree(pid):
            if not pid:
                return None
            
            cur.execute("SELECT id, ear_tag, father_id, mother_id, sex FROM pigs WHERE id=%s", (pid,))
            pig = cur.fetchone()
            if not pig:
                return None

            return {
                "name": pig["ear_tag"],
                "id": pig["id"],
                "sex": pig["sex"],  
                "children": list(filter(None, [
                    build_tree(pig["father_id"]),
                    build_tree(pig["mother_id"])
                ]))
            }

        tree = build_tree(pig_id)
    
    return jsonify(tree)

@app.route("/add_vaccine/<int:pig_id>", methods=["POST"])
def add_vaccine(pig_id):
    """为已存在的猪只添加疫苗"""
    vaccine_name = request.form.getlist("vaccine_name")
    vacc_dates = request.form.getlist("vacc_date")
    notes = request.form.getlist("vacc_notes")
    
    with get_db() as conn:
        cursor = conn.cursor()
        for name, date, note in zip(vaccine_name, vacc_dates, notes):
            if name and date:
                cursor.execute("""
                    INSERT INTO vaccinations (pig_id, vaccine, vacc_date, notes)
                    VALUES (%s, %s, %s, %s)
                    """, (pig_id, name, date, note))
        
    return redirect(f"/pig/{pig_id}")

def calculate_age_in_days(birth_date):
    """
    计算日龄：今天 - 出生日期
    """
    if not birth_date:
        return 0
    try:
        # 将字符串转为日期对象
        birth = datetime.strptime(str(birth_date), "%Y-%m-%d")
        # 获取当前日期
        today = datetime.now()
        # 计算差值的天数
        delta = today - birth
        return delta.days
    except:
        return 0 # 如果日期格式不对，返回0


app.jinja_env.filters['get_age'] = calculate_age_in_days

if __name__ == "__main__":
    app.run(debug=True)