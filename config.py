import os
from datetime import timedelta

# 获取当前文件（config.py）所在的目录，即 backend/
basedir = os.path.abspath(os.path.dirname(__file__))

class Config:
    # 1. 基础安全配置
    # 在本地开发如果没有设置 SECRET_KEY，会使用默认值 'dev_key'
    # 上线后建议在云托管后台设置一个复杂的 SECRET_KEY
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev_key_change_this_123456')
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY', 'dev_key_change_this_123456') 
    
    WX_APPID = 'wx2dc3181cfeec97ca'
    WX_SECRET = 'e9aecd7e83a30bdf92e353fe6bcf2901'   
    # 关闭 SQLAlchemy 的修改追踪，节省内存
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # =========================================================
    # 🟢 数据库配置 (自动切换逻辑)
    # =========================================================
    
    # 检查是否存在云托管注入的 MySQL 地址变量
    if os.environ.get('MYSQL_ADDRESS'):
        # --- 云端环境 (MySQL) ---
        print("🚀 [Config] 检测到云端环境，正在连接 MySQL...")
        
        # 获取环境变量 (这些变量需要在云托管控制台配置)
        mysql_user = os.environ.get('MYSQL_USERNAME', 'root')
        mysql_pass = os.environ.get('MYSQL_PASSWORD', 'root')
        mysql_addr = os.environ.get('MYSQL_ADDRESS', '127.0.0.1:3306')
        mysql_db   = os.environ.get('MYSQL_DATABASE', 'jijin')
        
        # 构造 MySQL 连接字符串 (使用 pymysql 驱动)
        SQLALCHEMY_DATABASE_URI = f'mysql+pymysql://{mysql_user}:{mysql_pass}@{mysql_addr}/{mysql_db}?charset=utf8mb4'
        
        # 🟢 强化版生产环境连接池配置
        SQLALCHEMY_ENGINE_OPTIONS = {
            "pool_pre_ping": True,   # 👈 核心：每次使用连接前先检查是否有效，断了就自动重连
            "pool_recycle": 120,     # 👈 缩短回收时间：如果连接空闲超过2分钟，则强制替换新连接
            "pool_size": 10,         
            "max_overflow": 20,
            "pool_timeout": 10       # 获取连接等待超时时间
        }
        
        
    else:
        # --- 本地环境 (SQLite) ---
        print("🐢 [Config] 检测到本地环境，使用 SQLite 文件")
        


        SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(basedir, 'app.db')
        
        JWT_ACCESS_TOKEN_EXPIRES = timedelta(days=7)
        SQLALCHEMY_TRACK_MODIFICATIONS = False

        REDIS_URL = "redis://localhost:6379/0"