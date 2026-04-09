from flask import Flask, render_template, request, redirect, jsonify, session, flash
from database import get_db, init_db
from services.inbreeding_service import get_all_pedigree, compute_inbreeding_A_matrix
import csv
import io
import pymysql
from datetime import datetime
import sys
from waitress import serve
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from flask import send_file


app = Flask(__name__)
app.secret_key = 'clonorgan_pigfarm'
app.config['SESSION_COOKIE_DOMAIN'] = None  
from datetime import timedelta

app.permanent_session_lifetime = timedelta(days=1) 


init_db()



def login_required(f):
    """无参数装饰器：限制只有登录用户才能访问"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated_function

def role_required(*allowed_roles):
    """
    带参数的装饰器：检查用户角色
    """

    def decorator(f):

        @wraps(f)
        def wrapper(*args, **kwargs):
    
            if 'user_id' not in session:
                return redirect('/login')
            
            if session.get('role') not in allowed_roles:
                return "权限不足", 403
            
            return f(*args, **kwargs)
        return wrapper
    return decorator

def log_action(action, details="", pig_id=None):
    """记录日志到数据库，支持关联猪只ID"""
    if 'user_id' in session:
        try:
            with get_db() as conn:
                cur = conn.cursor()

                cur.execute(
                    "INSERT INTO logs (user_id, action, details, pig_id) VALUES (%s, %s, %s, %s)",
                    (session['user_id'], action, details, pig_id)
                )
                conn.commit()
        except Exception as e:
            print(f"记录日志失败: {e}")
sys.setrecursionlimit(1000)


@app.route("/")
@login_required
def index():

    status_filter = request.args.get('status', '1')
    
    with get_db() as conn:
        cur = conn.cursor()
        

        sql = "SELECT * FROM pigs WHERE 1=1"
        params = []
        
        if status_filter:
            sql += " AND status=%s"
            params.append(status_filter)
            
        sql += " ORDER BY id DESC"
        
        cur.execute(sql, tuple(params))
        pigs = [dict(row) for row in cur.fetchall()]
        

        for pig in pigs:

            pig['current_weight'] = None
            pig['current_weigh_date'] = None
            
            try:

                cur.execute(
                    "SELECT weight, weigh_date FROM weights WHERE pig_id=%s ORDER BY weigh_date DESC LIMIT 1",
                    (pig['id'],)
                )
                w_row = cur.fetchone()
                
                if w_row:
                    pig['current_weight'] = w_row['weight']
                    pig['current_weigh_date'] = w_row['weigh_date']
            except Exception as e:

                print(f"查询猪只 {pig['id']} 体重历史失败: {e}")
                pig['current_weight'] = None


        for pig in pigs:
            if pig['current_weight'] is None:

                pig['current_weight'] = pig.get('weight')
                pig['current_weigh_date'] = pig.get('weigh_date')


        pedigree = get_all_pedigree(conn)
        all_F = compute_inbreeding_A_matrix(pedigree)
        
        for pig in pigs:
            if pig['id'] in all_F:
                pig['calculated_F'] = all_F[pig['id']]
            else:
                pig['calculated_F'] = 0.0


        cur.execute("SELECT DISTINCT breed FROM pigs WHERE breed IS NOT NULL AND breed != '' ORDER BY breed")
        breeds = [row["breed"] for row in cur.fetchall()]
        
        cur.execute("SELECT * FROM farms")
        farms = cur.fetchall()

    return render_template("index.html", pigs=pigs, breeds=breeds, farms=farms, role=session.get('role'))


@app.route("/pig/<int:pig_id>")
@login_required 
def pig(pig_id):

    with get_db() as conn:
        cur = conn.cursor(pymysql.cursors.DictCursor)
        

        cur.execute("SELECT * FROM pigs WHERE id=%s", (pig_id,))
        pig = cur.fetchone()
        
     
        clone_source_name = None
        if pig.get('is_clone') and pig.get('clone_source_id'):
            cur.execute("SELECT ear_tag FROM pigs WHERE id=%s", (pig['clone_source_id'],))
            source = cur.fetchone()
            if source:
                clone_source_name = source['ear_tag']

        surrogate_name = None
        if pig.get('surrogate_id'):

            surrogate_name = str(pig['surrogate_id']).strip()
        

        farm_name = "未知"
        if pig and pig.get("farm_id"):
            cur.execute("SELECT name FROM farms WHERE id=%s", (pig["farm_id"],))
            farm_row = cur.fetchone()
            if farm_row:
                farm_name = farm_row["name"]


        pedigree = get_all_pedigree(conn)
        all_F = compute_inbreeding_A_matrix(pedigree)
        current_F = all_F.get(pig_id, 0.0)
        pig['inbreeding'] = current_F

        cur.execute("SELECT * FROM phenotype WHERE pig_id=%s", (pig_id,))
        phenotypes = cur.fetchall()
        cur.execute("SELECT * FROM genotype WHERE pig_id=%s", (pig_id,))
        genotypes = cur.fetchall()
        

        cur.execute("SELECT * FROM vaccinations WHERE pig_id=%s ORDER BY vacc_date ASC", (pig_id,))
        vaccinations = cur.fetchall()
    

        cur.execute("SELECT * FROM weights WHERE pig_id=%s ORDER BY weigh_date ASC", (pig_id,))
        weights = cur.fetchall()

 
        for w in weights:
            if w.get('weight') is not None: w['weight'] = float(w['weight'])
            if w.get('weigh_date') is not None: w['weigh_date'] = str(w['weigh_date'])


        if weights:
            pig['current_weight'] = weights[-1]['weight']
        else:
            pig['current_weight'] = pig.get('weight')


        if pig.get('weight') and pig.get('weigh_date'):
            initial_date_str = str(pig['weigh_date'])
            

            if isinstance(weights, list):
                if not weights or (initial_date_str < weights[0]['weigh_date']):
                    initial_weight_record = {
                        'weigh_date': initial_date_str,
                        'weight': float(pig['weight']),
                        'notes': '初始登记体重'
                    }
                    weights.insert(0, initial_weight_record)
            else:
                print(f"DEBUG ERROR: weights is not a list, it is {type(weights)}")
        

        cur.execute("""
            SELECT logs.*, users.username 
            FROM logs 
            JOIN users ON logs.user_id = users.id 
            WHERE logs.pig_id = %s 
            ORDER BY logs.created_at DESC
        """, (pig_id,))
        pig_logs = cur.fetchall()

        return render_template("pig.html", pig=pig, phenotypes=phenotypes, genotypes=genotypes, 
                               vaccinations=vaccinations, farm_name=farm_name, pig_logs=pig_logs,
                               clone_source_name=clone_source_name, weights=weights)

@app.route("/add_pig", methods=["GET", "POST"])
@login_required
def add_pig():
    if session.get('role') == 'viewer':
        return "您没有权限执行此操作", 403


    current_farm_id = session.get('current_farm_id', 1)

    with get_db() as conn:
        cur = conn.cursor()
        
  
        cur.execute("SELECT id, ear_tag FROM pigs WHERE sex = 'M' AND status=1") 
        boars = cur.fetchall()
        
        cur.execute("SELECT id, ear_tag FROM pigs WHERE sex = 'F' AND status=1")
        sows = cur.fetchall()

 
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

  
        is_clone = 1 if data.get("is_clone") else 0
        clone_source_id = data.get("clone_source_id") or None
        surrogate_id = data.get("surrogate_name") or None

    
        blood_type = data.get("blood_type")
        weight = data.get("weight")
        weigh_date = data.get("weigh_date")
        #project_status = data.get("project_status")
        #project_notes = data.get("project_notes")
        theory_genotype = data.get("theory_genotype")
        #genotype_result = data.get("genotype_result")
        #phenotype_check = data.get("phenotype_check")
        pig_generation = data.get("pig_generation")
        dpf_generation = data.get("dpf_generation")
        #health_status = data.get("health_status")
        #health_desc = data.get("health_desc")
        #can_breed = data.get("can_breed")

       
        if is_clone and not clone_source_id:
            return "错误：标记为克隆猪时，必须选择克隆来源个体。"

        with get_db() as conn:
            cursor = conn.cursor()
            
      
            cursor.execute("""
                INSERT INTO pigs (
                    ear_tag, sex, breed, birth_date, father_id, mother_id, farm_id, 
                    is_clone, clone_source_id,
                    blood_type, weight, weigh_date, 
                    theory_genotype,
                    pig_generation, dpf_generation
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                ear_tag, sex, breed, birth_date, father_id, mother_id, farm_id, 
                is_clone, clone_source_id,
                blood_type, weight, weigh_date, 
                theory_genotype,
                pig_generation, dpf_generation
            ))
            
            pig_id = cursor.lastrowid

         
            vaccine_name = request.form.getlist("vaccine_name")
            vacc_dates = request.form.getlist("vacc_date")
            notes = request.form.getlist("vacc_notes")
            for name, date, note in zip(vaccine_name, vacc_dates, notes):
                if name and date:
                    cursor.execute("""
                        INSERT INTO vaccinations (pig_id, vaccine, vacc_date, notes)
                        VALUES (%s, %s, %s, %s)
                    """, (pig_id, name, date, note))

    
            pedigree = get_all_pedigree(conn)
            all_F = compute_inbreeding_A_matrix(pedigree)
            
         
            for pid, f_val in all_F.items():
                cursor.execute("UPDATE pigs SET inbreeding=%s WHERE id=%s", (f_val, pid))
            
                conn.commit() # 提交所有更改

        
            details_parts = [
                f"耳号:{ear_tag}",
                f"血型:{blood_type or '无'}",
                f"体重:{weight or '无'}kg",
                #f"项目:{project_status or '无'}",
                f"基因:{theory_genotype or '无'}", # 优先显示鉴定结果
                #f"健康:{health_status or '无'}"
            ]
            
            log_details = "新增登记 | " + " | ".join(details_parts)
            
            # 如果是克隆，加上克隆来源
            if is_clone and clone_source_id:
                cursor.execute("SELECT ear_tag FROM pigs WHERE id=%s", (clone_source_id,))
                source = cursor.fetchone()
                if source:
                    log_details += f" | 克隆自:{source['ear_tag']}"
            
            # 记录日志
            log_action("add_pig", log_details, pig_id=pig_id)

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
@login_required
def delete_pig(pig_id):
    if session.get('role') == 'viewer':
        return "您没有权限执行此操作", 403

    ear_tag_to_log = "未知" # 默认值

    with get_db() as conn:
        cursor = conn.cursor()
        
        # 【修复】先查出耳号，防止日志里显示不了
        cursor.execute("SELECT ear_tag FROM pigs WHERE id=%s", (pig_id,))
        result = cursor.fetchone()
        if result:
            ear_tag_to_log = result['ear_tag']

        # 执行删除
        cursor.execute("DELETE FROM vaccinations WHERE pig_id=%s", (pig_id,))
        cursor.execute("DELETE FROM phenotype WHERE pig_id=%s", (pig_id,))
        cursor.execute("DELETE FROM genotype WHERE pig_id=%s", (pig_id,))
        cursor.execute("DELETE FROM pigs WHERE id=%s", (pig_id,))
    
    log_action("delete_pig", f"删除猪只: 耳号 {ear_tag_to_log}", pig_id=pig_id)
    return redirect("/")

# 淘汰路由 
@app.route("/eliminate_pig/<int:pig_id>", methods=["POST"])
@login_required
def eliminate_pig(pig_id):
    """将猪只状态改为：淘汰"""
    ear_tag_to_log = "未知"
    
    with get_db() as conn:
        cur = conn.cursor()
        
        # 【修复】先查耳号
        cur.execute("SELECT ear_tag FROM pigs WHERE id=%s", (pig_id,))
        result = cur.fetchone()
        if result:
            ear_tag_to_log = result['ear_tag']

        # 更新状态
        cur.execute("UPDATE pigs SET status=2 WHERE id=%s", (pig_id,))
        
    log_action("status_change", f"淘汰猪只: 耳号 {ear_tag_to_log}", pig_id=pig_id)
    return redirect("/")

#  使用路由 
@app.route("/use_pig/<int:pig_id>", methods=["POST"])
@login_required
def use_pig(pig_id):
    """将猪只状态改为：使用"""
    ear_tag_to_log = "未知"
    
    with get_db() as conn:
        cur = conn.cursor()
        
        # 【修复】先查耳号
        cur.execute("SELECT ear_tag FROM pigs WHERE id=%s", (pig_id,))
        result = cur.fetchone()
        if result:
            ear_tag_to_log = result['ear_tag']

        # 更新状态
        cur.execute("UPDATE pigs SET status=3 WHERE id=%s", (pig_id,))
        
    # 【修复】动作名也改一下，更准确
    log_action("status_change", f"使用猪只: 耳号 {ear_tag_to_log}", pig_id=pig_id)
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
@login_required
def import_pigs():
    if request.method == "POST":
        file = request.files["file"]
        if not file:
            flash("未选择文件", "error")
            return redirect(request.url)
        
        file_content = file.stream.read()

        # 1. 解码
        stream = None
        try:
            stream = io.StringIO(file_content.decode("utf-8-sig"))
        except UnicodeDecodeError:
            try:
                stream = io.StringIO(file_content.decode("GBK"))
            except Exception as e:
                flash(f"文件解码错误: {e}", "error")
                return redirect(request.url)
            
        # 分隔符检测
        first_line = stream.readline()
        detected_delimiter = ','
        if ';' in first_line: detected_delimiter = ';'
        elif '\t' in first_line: detected_delimiter = '\t'
        stream.seek(0)
        
        try:
            reader = csv.DictReader(stream, delimiter=detected_delimiter)
            if reader.fieldnames:
                reader.fieldnames = [name.strip() for name in reader.fieldnames]
        except Exception as e:
            flash(f"CSV 解析错误: {e}", "error")
            return redirect(request.url)

        with get_db() as conn:
            cur = conn.cursor()
            
            # 获取现有牧场
            cur.execute("SELECT id, name FROM farms")
            farms = cur.fetchall()
            farm_map = {row["name"]: row["id"] for row in farms}
            current_farm_id = session.get('current_farm_id', 1)

            # 获取现有猪只（用于判断重复）
            cur.execute("SELECT id, ear_tag FROM pigs")
            existing_pigs = cur.fetchall()
            existing_pig_map = {row["ear_tag"]: row["id"] for row in existing_pigs}

            import_batch = [] # 存储本次导入的猪的信息 {ear_tag, id, father_tag, mother_tag}
            error_logs = []

            print(">>> 开始处理导入...")

            for row in reader:
                try:
                    ear_tag = row.get("ear_tag", "").strip()
                    if not ear_tag:
                        continue

                    # 检查是否已存在
                    if ear_tag in existing_pig_map:
                        error_logs.append(f"耳标 {ear_tag} 已存在数据库中，跳过导入。")
                        continue

                    sex = row.get("sex", "").strip()
                    breed = row.get("breed", "").strip()
                    birth_date = row.get("birth_date", "").strip()
                    if not birth_date: birth_date = None
                    
                    weigh_date = row.get("weigh_date", "").strip()
                    if not weigh_date: weigh_date = None
                    
                    blood_type = row.get("blood_type", "").strip() or None
                    weight = row.get("weight", "").strip()
                    if not weight: weight = None
                    
                    project_status = row.get("project_status", "").strip() or None
                    project_notes = row.get("project_notes", "").strip() or None
                    theory_genotype = row.get("theory_genotype", "").strip() or None
                    genotype_result = row.get("genotype_result", "").strip() or None
                    phenotype_check = row.get("phenotype_check", "").strip() or None
                    pig_generation = row.get("pig_generation")
                    if pig_generation is not None: pig_generation = pig_generation.strip() or None
                    dpf_generation = row.get("dpf_generation")
                    if dpf_generation is not None: dpf_generation = dpf_generation.strip() or None
                    health_status = row.get("health_status", "").strip() or None
                    health_desc = row.get("health_desc", "").strip() or None
                    can_breed = row.get("can_breed", "").strip() or None

                    # 牧场ID
                    farm_name_str = row.get("farm_name", "").strip()
                    target_farm_id = farm_map.get(farm_name_str, current_farm_id)

                    # 执行插入 (父母暂时设为 None)
                    cur.execute(
                        """INSERT INTO pigs (
                            ear_tag, sex, breed, birth_date, father_id, mother_id, farm_id,
                            blood_type, weight, weigh_date, project_status, project_notes,
                            theory_genotype, genotype_result, phenotype_check,
                            pig_generation, dpf_generation, health_status, health_desc, can_breed
                        ) VALUES (%s,%s,%s,%s,%s,%s,%s, %s,%s,%s,%s,%s, %s,%s,%s, %s,%s,%s,%s,%s)""",
                        (ear_tag, sex, breed, birth_date, None, None, target_farm_id, 
                         blood_type, weight, weigh_date, project_status, project_notes,
                         theory_genotype, genotype_result, phenotype_check,
                         pig_generation, dpf_generation, health_status, health_desc, can_breed)
                    )
                    
                    new_id = cur.lastrowid
                    
                    # 记录到批次列表，包含 CSV 中填写的父母耳标（用于后续匹配）
                    import_batch.append({
                        "id": new_id,
                        "ear_tag": ear_tag,
                        "father_tag": row.get("father_tag", "").strip() if row.get("father_tag") else "",
                        "mother_tag": row.get("mother_tag", "").strip() if row.get("mother_tag") else ""
                    })

                    log_action("import_pig", f"导入猪只: {ear_tag}", pig_id=new_id)

                except pymysql.IntegrityError as e:
                    # 这里可能是外键约束错误，或者是唯一索引冲突
                    error_logs.append(f"耳标 {ear_tag} 插入失败 (可能外键错误或重复): {e}")
                except Exception as e:
                    error_logs.append(f"行 {ear_tag} 处理异常: {e}")

            conn.commit()
            
            if error_logs:
                for err in error_logs:
                    print(f"ERROR: {err}") # 在控制台打印详细错误

            # --- 第二步：更新父母关系 ---
            # 此时 import_batch 里的猪已经都在数据库里了
            # 我们需要构建一个包含【数据库旧猪 + 本次新猪】的完整 Map
            full_pig_map = existing_pig_map.copy()
            for item in import_batch:
                full_pig_map[item["ear_tag"]] = item["id"]

            update_count = 0
            missing_parents_count = 0

            for item in import_batch:
                father_tag = item["father_tag"]
                mother_tag = item["mother_tag"]
                
                father_id = full_pig_map.get(father_tag)
                mother_id = full_pig_map.get(mother_tag)

                if father_id is not None or mother_id is not None:
                    try:
                        cur.execute(
                            "UPDATE pigs SET father_id=%s, mother_id=%s WHERE id=%s",
                            (father_id, mother_id, item["id"])
                        )
                        update_count += 1
                    except Exception as e:
                        print(f"更新父母关系失败 ({item['ear_tag']}): {e}")
                else:
                    if father_tag or mother_tag:
                        # 如果填了父母但找不到，记录一下
                        missing_parents_count += 1
            
            conn.commit()

            # --- 第三步：计算近交系数 (代码同前) ---
            try:
                pedigree = get_all_pedigree(conn)
                all_F = compute_inbreeding_A_matrix(pedigree)
                calc_count = 0
                for item in import_batch:
                    try:
                        F_new = all_F.get(item["id"], 0.0)
                        cur.execute("UPDATE pigs SET inbreeding=%s WHERE id=%s", (F_new, item["id"]))
                        calc_count += 1
                    except: pass
                conn.commit()
            except: calc_count = 0

        msg = f"成功导入 {len(import_batch)} 头猪。"
        if update_count > 0:
            msg += f"关联父母 {update_count} 个。"
        if missing_parents_count > 0:
            msg += f"警告：{missing_parents_count} 头猪的父母耳标在系统中找不到。"
        if error_logs:
            msg += f" 失败 {len(error_logs)} 条。"
            
        flash(msg, "success" if not error_logs else "warning")
        return redirect(f"/?imported={len(import_batch)}&linked={update_count}&calc={calc_count}")

    return render_template("import.html")

@app.route("/pedigree/<int:pig_id>")
def pedigree(pig_id):
    with get_db() as conn:
        # 依然需要 DictCursor，否则 pig["ear_tag"] 会报错
        cur = conn.cursor(pymysql.cursors.DictCursor)

        def build_tree(pid):
            # 1. 只要 ID 存在，就继续查，不再检查 visited
            if not pid:
                return None
            
            try:
                cur.execute("SELECT id, ear_tag, father_id, mother_id, sex FROM pigs WHERE id=%s", (pid,))
                pig = cur.fetchone()
            except Exception as e:
                return None

            if not pig:
                return None

            # 2. 继续递归查找父亲和母亲
            # 直到数据库中 father_id 或 mother_id 为空，递归才会自然停止
            father_node = build_tree(pig["father_id"])
            mother_node = build_tree(pig["mother_id"])

            return {
                "name": pig["ear_tag"],
                "id": pig["id"],
                "sex": pig["sex"],
                "children": [node for node in [father_node, mother_node] if node is not None]
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
    log_action("add_vaccine", f"为猪只 ID: {pig_id} 添加了疫苗", pig_id=pig_id)
   
    return redirect(f"/pig/{pig_id}")

@app.route("/add_weight/<int:pig_id>", methods=["POST"])
@login_required
def add_weight(pig_id):
    dates = request.form.getlist("weight_date")
    vals = request.form.getlist("weight_val")
    notes = request.form.getlist("weight_notes")

    if not dates or not vals:
        return "请输入至少一条记录", 400

    with get_db() as conn:
        cursor = conn.cursor()
        
        # 1. 循环插入历史记录到 weights 表
        inserted_count = 0
        
        for i in range(len(dates)):
            d = dates[i].strip()
            v = vals[i].strip()
            n = notes[i].strip() if i < len(notes) else ""

            if not d or not v:
                continue

            cursor.execute("""
                INSERT INTO weights (pig_id, weight, weigh_date, notes)
                VALUES (%s, %s, %s, %s)
                """, (pig_id, v, d, n))
            inserted_count += 1
        
        # 2. 【关键修改】这里删除了 UPDATE pigs SET weight=... 的代码
        # 之前的逻辑是：添加新体重后，会把 pigs.weight 更新为最新的体重。
        # 现在的逻辑：不再更新 pigs.weight，让它永远保持“初始录入”的值。
        # 列表页显示的 weight 将始终是这头猪“出生/入栏”时的体重。
        
        conn.commit() 
        
    log_action("add_weight", f"为猪只 ID: {pig_id} 添加了 {inserted_count} 条体重记录", pig_id=pig_id)
    return redirect(f"/pig/{pig_id}")

@app.route("/delete_weight/<int:weight_id>", methods=["GET", "POST"]) 
@login_required
def delete_weight(weight_id):
    with get_db() as conn:
        cur = conn.cursor()
        # 1. 先查一下这条记录属于哪头猪，为了删除后能跳转回去
        cur.execute("SELECT pig_id FROM weights WHERE id=%s", (weight_id,))
        res = cur.fetchone()
        
        if not res:
            return "记录不存在或已被删除", 404
            
        pig_id = res['pig_id']
        
        # 2. 执行删除
        cur.execute("DELETE FROM weights WHERE id=%s", (weight_id,))
        conn.commit()
        
        # 记录日志
        log_action("delete_weight", f"删除了体重记录 ID: {weight_id}", pig_id=pig_id)
        
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





# --------------------
# 认证路由
# --------------------

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        
        print(f"尝试登录用户: {username}") # 调试1
        
        with get_db() as conn:
            cur = conn.cursor(pymysql.cursors.DictCursor)
            cur.execute("SELECT * FROM users WHERE username=%s", (username,))
            user = cur.fetchone()
            
            if user and check_password_hash(user['password'], password):
                session['user_id'] = user['id']
                session['username'] = user['username']
                session['role'] = user['role']
                
                print(f"登录成功！Session ID: {session.get('user_id')}") # 调试2
                
                log_action("login", "用户登录系统")
                return redirect("/")
            else:
                print("密码错误或用户不存在") # 调试3
                return "用户名或密码错误"
                
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

@app.route("/logs")
@login_required
@role_required('admin')
def view_logs():
    # 1. 尝试从 URL 参数中获取 pig_id (例如 /logs?pig_id=123)
    pig_id = request.args.get('pig_id', type=int)

    with get_db() as conn:
        cur = conn.cursor(pymysql.cursors.DictCursor)
        
        # 2. 基础 SQL (先不加 WHERE)
        sql = """
            SELECT logs.*, users.username 
            FROM logs 
            JOIN users ON logs.user_id = users.id 
        """
        params = []

        # 3. 如果 URL 里有 pig_id，就加上 WHERE 条件
        if pig_id:
            sql += " WHERE logs.pig_id = %s"
            params.append(pig_id)
        
        sql += " ORDER BY logs.created_at DESC"
        
        cur.execute(sql, tuple(params))
        logs = cur.fetchall()
        
    # 4. 把 pig_id 传给模板，方便修改页面标题
    return render_template("logs.html", logs=logs, current_pig_id=pig_id)

# 添加用户路由 (仅管理员可访问)
@app.route("/add_user", methods=["GET", "POST"])
@login_required
@role_required('admin')  # 只有 admin 能进这个页面
def add_user():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        role = request.form.get("role")

        if not username or not password:
            return "用户名和密码不能为空", 400

        # 密码加密存储 (非常重要，不能存明文)
        pw_hash = generate_password_hash(password)

        try:
            with get_db() as conn:
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO users (username, password, role) VALUES (%s, %s, %s)",
                    (username, pw_hash, role)
                )
                conn.commit()
            log_action("add_user", f"添加了新用户: {username}, 角色: {role}")
            return redirect("/manage_users")  # 添加成功后跳转到用户列表
        except pymysql.IntegrityError:
            return "错误：该用户名已存在，请换个用户名。"
        except Exception as e:
            return f"添加失败: {e}"

    return render_template("add_user.html")

# 用户列表路由 (仅管理员可访问)
@app.route("/manage_users")
@login_required
@role_required('admin')
def manage_users():
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, username, role FROM users ORDER BY id ASC")
        users = cur.fetchall()
    return render_template("manage_users.html", users=users)

# 强制重置管理员密码的临时工具
@app.route("/reset_admin")
def reset_admin():
    """
    访问此页面将强制重置管理员密码为 123456
    """
    new_hash = generate_password_hash("123456")
    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("UPDATE users SET password=%s WHERE username=%s", (new_hash, "admin"))
            conn.commit()
        return "<h1>密码重置成功！</h1>管理员 (admin) 的密码已重置为: <b>123456</b><br><a href='/login'>点击这里去登录</a>"
    except Exception as e:
        return f"重置失败: {e}"

@app.route("/init_admin")
def init_admin():
    # 创建一个默认管理员：用户名 admin，密码 123456
    pw_hash = generate_password_hash("123456")
    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("INSERT INTO users (username, password, role) VALUES (%s, %s, %s)", 
                       ("admin", pw_hash, "admin"))
            conn.commit()
        return "管理员创建成功！<br>用户名: <b>admin</b><br>密码: <b>123456</b><br><a href='/login'>点击这里去登录</a>"
    except Exception as e:
        return f"创建失败（可能管理员已存在）: {e}<br><a href='/login'>点击这里去登录</a>"



# 重置用户密码路由 (仅管理员可访问)
@app.route("/reset_password/<int:user_id>", methods=["POST"])
@login_required
@role_required('admin')
def reset_user_password(user_id):
    # 生成一个简单的默认密码的哈希值
    default_password = "123456"
    pw_hash = generate_password_hash(default_password)

    try:
        with get_db() as conn:
            cur = conn.cursor()
            # 防止管理员误删自己或者重置自己（可选）
            if user_id == session.get('user_id'):
                return "你不能重置自己的密码，请去个人设置修改。"

            cur.execute(
                "UPDATE users SET password=%s WHERE id=%s",
                (pw_hash, user_id)
            )
            conn.commit()
        
        # 记录日志
        # 先查一下这个用户是谁，方便记日志
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT username FROM users WHERE id=%s", (user_id,))
            user = cur.fetchone()
            username = user['username'] if user else "未知用户"
        
        log_action("reset_password", f"管理员重置了用户 {username} (ID:{user_id}) 的密码")
        
        # 重定向回用户列表页面
        return redirect("/manage_users")
        
    except Exception as e:
        return f"重置失败: {e}"

# 临时修复路由：给 logs 表加上 pig_id 列
@app.route("/update_db_structure")
def update_db_structure():
    try:
        with get_db() as conn:
            cur = conn.cursor()
            # 这条 SQL 会在现有的 logs 表里加一列
            cur.execute("ALTER TABLE logs ADD COLUMN pig_id INT DEFAULT NULL")
            conn.commit()
        return "<h1>✅ 修复成功！</h1>数据库已添加 pig_id 列。<br><a href='/'>返回首页</a>"
    except Exception as e:
        return f"❌ 修复失败（可能已经修复过了）: {e}"

@app.route("/update_pig_info/<int:pig_id>", methods=["POST"])
@login_required
@role_required('admin', 'operator')  # 只有管理员和操作员能修改
def update_pig_info(pig_id):
    data = request.form
    
    # 获取表单数据
    project_status = data.get("project_status")
    project_notes = data.get("project_notes")
    genotype_result = data.get("genotype_result")
    phenotype_check = data.get("phenotype_check")
    health_status = data.get("health_status")
    health_desc = data.get("health_desc")
    can_breed = data.get("can_breed")
    
    with get_db() as conn:
        cur = conn.cursor()
        try:
            cur.execute("""
                UPDATE pigs SET 
                    project_status = %s,
                    project_notes = %s,
                    genotype_result = %s,
                    phenotype_check = %s,
                    health_status = %s,
                    health_desc = %s,
                    can_breed = %s
                WHERE id = %s
            """, (project_status, project_notes, genotype_result, phenotype_check, 
                  health_status, health_desc, can_breed, pig_id))
            conn.commit()
            log_action("update_info", f"修改了猪只 ID: {pig_id} 的详细信息", pig_id=pig_id)
        except Exception as e:
            return f"更新失败: {e}"
            
    return redirect(f"/pig/{pig_id}")

@app.route("/export_pigs")
@login_required
def export_pigs():
    """
    导出猪只数据（完全匹配列表页表头）
    """
    ids_str = request.args.get('ids') 
    
    # 1. 构建 SQL：查询 pigs 表所有字段，并关联 farms 表获取厂区名称
    sql = """
        SELECT p.*, f.name as farm_name 
        FROM pigs p 
        LEFT JOIN farms f ON p.farm_id = f.id 
        WHERE 1=1
    """
    params = []

    if ids_str:
        try:
            ids = [int(x.strip()) for x in ids_str.split(',')]
            placeholders = ','.join(['%s'] * len(ids))
            sql += f" AND p.id IN ({placeholders})"
            params.extend(ids)
        except ValueError:
            return "导出参数错误"
            
    else:
        export_all = request.args.get('all', '0') == '1'
        status_filter = request.args.get('status', '1') if not export_all else None

        if not export_all and status_filter:
            sql += " AND p.status=%s"
            params.append(status_filter)
            
    sql += " ORDER BY p.id ASC"

    # 2. 执行查询
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(sql, tuple(params))
        rows = cur.fetchall()

    # 3. 定义辅助函数：计算日龄
    def calculate_age(birth_date_str):
        if not birth_date_str:
            return ""
        try:
            from datetime import datetime
            birth = datetime.strptime(str(birth_date_str), "%Y-%m-%d")
            today = datetime.now()
            return (today - birth).days
        except:
            return ""

    # 4. 准备表头（严格按照 HTML 顺序，忽略 checkbox 和 #）
    headers = [
        'ID', '耳号', '性别', '品种', '理论基因型', '基因鉴定结果', '出生日期', 
        '日龄 (天)', '厂区', '近交系数', '血型', '体重', '称量时间', '项目状态', 
        '安排信息备注', '表型验证', '健康状况', '代次 (F)', 'DPF代次'
    ]
    
    # 5. 生成 CSV
    output = io.StringIO()
    output.write('\ufeff') # 添加 BOM 防止 Excel 打开乱码
    writer = csv.writer(output)
    
    writer.writerow(headers)
    
    sex_map = {'M': '公', 'F': '母'}

    for row in rows:
        # 计算日龄
        age_days = calculate_age(row['birth_date'])
        
        # 处理近交系数（保留4位小数）
        f_val = round(row['inbreeding'], 4) if row['inbreeding'] is not None else 0
        
        # 按照表头顺序组织每一行的数据
        row_data = [
            row['id'],                                    # ID
            row['ear_tag'],                               # 耳号
            sex_map.get(row['sex'], row['sex']),          # 性别 (中文)
            row['breed'],                                 # 品种
            row.get('theory_genotype', ''),               # 理论基因型
            row.get('genotype_result', ''),               # 基因鉴定结果
            row['birth_date'],                            # 出生日期
            age_days,                                    # 日龄 (天)
            row.get('farm_name', ''),                     # 厂区
            f_val,                                       # 近交系数
            row.get('blood_type', ''),                    # 血型
            row.get('weight', ''),                        # 体重 (初始固定体重)
            row.get('weigh_date', ''),                    # 称量时间
            row.get('project_status', ''),                # 项目状态
            row.get('project_notes', ''),                 # 安排信息备注
            row.get('phenotype_check', ''),               # 表型验证
            row.get('health_status', ''),                 # 健康状况
            row.get('pig_generation', ''),                # 代次
            row.get('dpf_generation', '')                 # DPF代次
        ]
        
        writer.writerow(row_data)
    
    output.seek(0)
    
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"pigs_export_{timestamp}.csv"
    
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=filename
    )

@app.route("/export_logs")
@login_required
@role_required('admin')  # 只有管理员能导出日志
def export_logs():
    """
    导出操作日志 (仅 Admin)
    """
    pig_id = request.args.get('pig_id', type=int)

    with get_db() as conn:
        cur = conn.cursor()
        
        sql = """
            SELECT logs.id, logs.created_at, users.username, logs.action, logs.details, logs.pig_id
            FROM logs 
            JOIN users ON logs.user_id = users.id 
        """
        params = []
        if pig_id:
            sql += " WHERE logs.pig_id = %s"
            params.append(pig_id)
        sql += " ORDER BY logs.created_at DESC"
        
        cur.execute(sql, tuple(params))
        rows = cur.fetchall()

    output = io.StringIO()
    output.write('\ufeff') # 防乱码
    writer = csv.writer(output)
    
    # 日志表头
    writer.writerow(['日志ID', '时间', '操作人', '动作类型', '详细信息', '关联猪ID'])
    
    for row in rows:
        writer.writerow([
            row['id'],
            row['created_at'],
            row['username'],
            row['action'],
            row['details'],
            row['pig_id']
        ])
        
    output.seek(0)
    
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"system_logs_{timestamp}.csv"
    
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=filename
    )


if __name__ == "__main__":
    # --- 调试开发时用这个 (改代码自动重启) ---
    app.run(host='0.0.0.0', port=5000, debug=True)
    
    # --- 正式用时用这个 (更稳定，但改代码要手动重启) ---
    #serve(app, host='0.0.0.0', port=5000)
