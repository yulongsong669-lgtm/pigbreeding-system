import pymysql
from contextlib import contextmanager

# 数据库配置
DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "123456",
    "db": "pig_farm",
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor
}

def get_db_connection():
    conn = pymysql.connect(**DB_CONFIG)
    return conn

@contextmanager
def get_db():
    conn = get_db_connection()
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    sql_commands = """
    -- 1. 先创建厂区表
    CREATE TABLE IF NOT EXISTS farms(
        id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(50) NOT NULL
    );

    -- 2. 插入默认厂区
    INSERT IGNORE INTO farms (id, name) VALUES (1, '一期'), (2, '二期'), (3, '三期');

    -- 3. 创建猪只表 
    CREATE TABLE IF NOT EXISTS pigs(
        id INT AUTO_INCREMENT PRIMARY KEY,
        ear_tag VARCHAR(50) UNIQUE,
        sex CHAR(1),
        breed VARCHAR(50),
        birth_date DATE,
        father_id INT,
        mother_id INT,
        inbreeding DOUBLE DEFAULT 0.0,
        group_id INT,
        notes TEXT,
        farm_id INT DEFAULT 1,
        FOREIGN KEY(father_id) REFERENCES pigs(id),
        FOREIGN KEY(mother_id) REFERENCES pigs(id)
    );

    -- 4. 其他表
    CREATE TABLE IF NOT EXISTS mating(
        id INT AUTO_INCREMENT PRIMARY KEY,
        boar_id INT,
        sow_id INT,
        mating_date DATE,
        method VARCHAR(50),
        FOREIGN KEY(boar_id) REFERENCES pigs(id),
        FOREIGN KEY(sow_id) REFERENCES pigs(id)
    );

    CREATE TABLE IF NOT EXISTS litter(
        id INT AUTO_INCREMENT PRIMARY KEY,
        mating_id INT,
        birth_date DATE,
        total_born INT,
        born_alive INT,
        stillborn INT,
        weaned INT,
        FOREIGN KEY(mating_id) REFERENCES mating(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS phenotype(
        id INT AUTO_INCREMENT PRIMARY KEY,
        pig_id INT,
        trait VARCHAR(50),
        value DOUBLE,
        record_date DATE,
        FOREIGN KEY(pig_id) REFERENCES pigs(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS genotype(
        id INT AUTO_INCREMENT PRIMARY KEY,
        pig_id INT,
        marker VARCHAR(50),
        genotype VARCHAR(50),
        FOREIGN KEY(pig_id) REFERENCES pigs(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS vaccinations(
        id INT AUTO_INCREMENT PRIMARY KEY,
        pig_id INT,
        vaccine VARCHAR(100),
        vacc_date DATE,
        notes TEXT,
        FOREIGN KEY(pig_id) REFERENCES pigs(id) ON DELETE CASCADE
    );
    """

    for command in sql_commands.split(';'):
        command = command.strip()
        if command:
            try:
                cursor.execute(command)
            except Exception as e:
                print(f"执行SQL出错: {e}")

    conn.commit()
    conn.close()