from . import db
from datetime import datetime

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    openid = db.Column(db.String(128), unique=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class FundGroup(db.Model):
    """
    用户自定义分组配置表
    注意：不存储 '全部'，也可能不存储 '默认账户'(视初始化策略而定，建议存储以维护排序)
    """
    __tablename__ = 'fund_groups'
    id = db.Column(db.Integer, primary_key=True)
    
    # 关联用户
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # 分组名称
    name = db.Column(db.String(32), nullable=False)
    
    # 排序权重 (越小越靠前)
    sort_order = db.Column(db.Integer, default=0)

    # 联合唯一索引：同一个用户下分组名不能重复
    __table_args__ = (
        db.UniqueConstraint('user_id', 'name', name='uix_user_group_name'),
    )

# app/models.py

class FundAsset(db.Model):
    __tablename__ = 'fund_assets'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))

    fund_name = db.Column(db.String(128))
    holding_shares = db.Column(db.Float, default=0.0)
    cost_price = db.Column(db.Float, default=0.0)

    fund_code = db.Column(db.String(10), index=True)  # 基金 6 位代码
    fund_key = db.Column(db.String(50))              # 🚀 蚂蚁基金唯一 ID (e.g., '1.002207')

    
    # 🟢 彻底抛弃 platform，改用 group_name
    group_name = db.Column(db.String(32), default='默认账户', nullable=False) 

    # 🟢 索引同步更新
    __table_args__ = (
        db.UniqueConstraint('user_id', 'fund_code', 'group_name', name='uix_user_fund_group'),
    )