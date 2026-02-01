from app import create_app, db
from app.models import User, FundAsset, FundGroup, Fund # 🟢 显式导入模型，确保建表时能识别到它们

app = create_app()

# 🟢 关键修改：利用应用上下文自动建表
# 每次容器启动时，这段代码都会执行，自动检测并创建缺失的表
with app.app_context():
    try:
        db.create_all()
        print("✅ 数据库表结构同步完成")
    except Exception as e:
        print(f"⚠️ 建表失败 (可能是数据库连接问题): {e}")

# 下面这部分只在本地开发 ('python run.py') 时生效
# 云托管上是用 Gunicorn 启动的，不会走这里，所以不用删
if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True, port=5000)