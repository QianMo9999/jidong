from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import JWTManager
from . import Config
from flask import Flask
from flask_apscheduler import APScheduler

db = SQLAlchemy()
jwt = JWTManager()
scheduler = APScheduler()

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    jwt.init_app(app)

    # 注册蓝图
    from .routes.auth import auth_bp
    from .routes.assets import assets_bp
    from .routes.ocr import ocr_bp
    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(assets_bp, url_prefix='/api/assets')
    app.register_blueprint(ocr_bp, url_prefix='/api/ocr')
    

    with app.app_context():
        db.create_all()  # 自动创建数据库表

    # ==========================
    # 🟢 配置定时任务
    # ==========================
    # 开启 API 支持 (可选，允许你通过 HTTP 查看任务状态)
    app.config['SCHEDULER_API_ENABLED'] = False
    
    # 初始化
    scheduler.init_app(app)
    scheduler.start()
    
    # 🟢 添加任务：每天凌晨 2:00 更新一次
    # id: 任务唯一标识
    # func: 目标函数的引用路径
    # trigger: 'interval' (间隔) 或 'cron' (特定时间)
    @scheduler.task('cron', id='update_funds_job', hour=2, minute=0)
    def run_update_job():
        # 注意：这里需要手动推入应用上下文，否则无法访问 current_app (虽然上面的 TaskService 没用到 db，但为了稳健最好加上)
        with app.app_context():
            from .services.task_service import TaskService
            TaskService.update_fund_json()

    return app