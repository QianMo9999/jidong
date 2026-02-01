from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_apscheduler import APScheduler
from config import Config

# 初始化扩展
db = SQLAlchemy()
scheduler = APScheduler()

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # 1. 初始化数据库
    db.init_app(app)

    # 🟢 提示：由于不再使用 JWT，你可以去 config.py 里删掉 JWT_SECRET_KEY 以精简配置

    # 2. 注册蓝图 (路由)
    from .routes.auth import auth_bp
    from .routes.assets import assets_bp
    from .routes.ocr import ocr_bp
    
    # 注意：url_prefix 保持一致，前端 request.js 会自动拼接 /api
    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(assets_bp, url_prefix='/api/assets')
    app.register_blueprint(ocr_bp, url_prefix='/api/ocr')

    # 3. 同步数据库表结构
    with app.app_context():
        try:
            db.create_all()
            # print("✅ 数据库表结构同步/检查完成")
        except Exception as e:
            # 忽略“表已存在”错误，确保多进程启动不崩溃
            if 'already exists' in str(e).lower():
                pass
            else:
                print(f"❌ 数据库初始化异常: {str(e)}")
                # 在生产环境下通常不直接 raise，防止容器无限重启，但关键错误建议打印

    # 4. 配置定时任务 (APScheduler)
    # 开启 API 支持 (如果需要通过 /scheduler 路径查看任务，请设为 True)
    app.config['SCHEDULER_API_ENABLED'] = False
    
    # 只有在主进程中启动 Scheduler (防止 Gunicorn 多进程下重复执行任务)
    # 微信云托管通常单实例运行，如果后续有多实例需求，建议使用 Redis 锁
    if not scheduler.running:
        scheduler.init_app(app)
        scheduler.start()
    
    # 🟢 每天凌晨 2:00 执行基金数据更新任务
    @scheduler.task('cron', id='update_funds_job', hour=2, minute=0)
    def run_update_job():
        with app.app_context():
            try:
                from .services.task_service import TaskService
                print("⏰ 开始执行定时任务：更新基金 JSON 数据...")
                TaskService.update_fund_json()
                print("✅ 定时任务执行成功")
            except Exception as e:
                print(f"❌ 定时任务执行失败: {str(e)}")

    return app