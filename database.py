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
    
    CREATE TABLE IF NOT EXISTS farms(
        id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(50) NOT NULL
    );


    INSERT IGNORE INTO farms (id, name) VALUES (1, '一期'), (2, '二期'), (3, '三期');


    CREATE TABLE IF NOT EXISTS pigs(
        id INT AUTO_INCREMENT PRIMARY KEY,
        ear_tag VARCHAR(50) UNIQUE,
        sex CHAR(1),
        blood_type VARCHAR(20) DEFAULT NULL,
        breed VARCHAR(50),
        birth_date DATE,
        weight DECIMAL(10,2) DEFAULT NULL,
        weigh_date DATE DEFAULT NULL,
        father_id INT,
        mother_id INT,
        inbreeding DOUBLE DEFAULT 0.0,
        status INT DEFAULT 1,
        group_id INT,
        notes TEXT,
        farm_id INT DEFAULT 1,
        is_clone TINYINT(1) DEFAULT 0,
        clone_source_id INT DEFAULT NULL,
        surrogate_id INT DEFAULT NULL,
        project_status VARCHAR(20) DEFAULT NULL,
        project_notes TEXT,
        theory_genotype VARCHAR(100) DEFAULT NULL,
        genotype_result VARCHAR(100) DEFAULT NULL,
        phenotype_check VARCHAR(10) DEFAULT NULL,
        pig_generation INT DEFAULT NULL,
        dpf_generation INT DEFAULT NULL,
        health_status VARCHAR(20) DEFAULT NULL,
        health_desc TEXT,
        can_breed VARCHAR(10) DEFAULT NULL,
        FOREIGN KEY(father_id) REFERENCES pigs(id),
        FOREIGN KEY(mother_id) REFERENCES pigs(id)
    );


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

    CREATE TABLE IF NOT EXISTS users (
        id INT AUTO_INCREMENT PRIMARY KEY,
        username VARCHAR(50) NOT NULL UNIQUE,
        password VARCHAR(255) NOT NULL,
        role ENUM('admin', 'operator', 'viewer') NOT NULL DEFAULT 'viewer'
    );

    CREATE TABLE IF NOT EXISTS logs (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT,
        action VARCHAR(50),
        details TEXT,
        pig_id INT DEFAULT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS weights (
        id INT AUTO_INCREMENT PRIMARY KEY,
        pig_id INT,
        weight DECIMAL(10,2),
        weigh_date DATE,
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
