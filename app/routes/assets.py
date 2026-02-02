from flask import Blueprint, request, jsonify
from ..models import db, FundAsset, FundGroup, User
from ..services.market import MarketService
import traceback

assets_bp = Blueprint('assets', __name__)

# 系统常量
DEFAULT_GROUP_NAME = '默认账户'
ALL_GROUP_NAME = '全部'

# ==========================================
# 🛡️ 辅助函数：通过微信 Header 获取用户 ID
# ==========================================
def get_current_user_id():
    """
    通过云托管注入的 x-wx-openid 识别用户
    依靠 SQLALCHEMY_ENGINE_OPTIONS 中的 pool_pre_ping 自动重连 MySQL
    """
    openid = request.headers.get('x-wx-openid')
    if not openid:
        return 1 # 本地调试默认用户
    
    user = User.query.filter_by(openid=openid).first()
    if not user:
        try:
            user = User(openid=openid)
            db.session.add(user)
            db.session.commit()
        except Exception:
            db.session.rollback()
            user = User.query.filter_by(openid=openid).first()
    return user.id

# ==========================================
# 📈 行情与列表接口 (核心)
# ==========================================

@assets_bp.route('/list', methods=['GET'])
def list_assets():
    """获取资产列表：包含批量行情抓取和盈亏计算"""
    user_id = get_current_user_id()
    assets = FundAsset.query.filter_by(user_id=user_id).all()
    
    # 批量抓取行情
    # codes = [a.fund_code for a in assets]
    fund_items = [
        {'code': asset.fund_code, 'key': asset.fund_key} 
        for asset in assets
    ]
    quotes = MarketService.batch_get_valuation(fund_items) if codes else {}
    
    total_val = 0
    day_profit = 0
    funds = []

    for a in assets:
        mkt = quotes.get(a.fund_code, {})
        nav = float(mkt.get('nav', 1.0))
        daily_pct = float(mkt.get('gszzl', 0.0)) # 注意对应批量接口字段
        
        cur_val = a.holding_shares * nav
        # 根据实时涨跌幅反推当日收益
        d_profit = (cur_val / (1 + daily_pct/100)) * (daily_pct/100) if daily_pct != -100 else -cur_val
        
        total_val += cur_val
        day_profit += d_profit

        funds.append({
            "id": a.id,
            "fund_name": a.fund_name,
            "fund_code": a.fund_code,
            "group_name": a.group_name or DEFAULT_GROUP_NAME,
            "market_value": "{:.2f}".format(cur_val),
            "current_nav": nav,
            "daily_pct": daily_pct,
            "day_profit": round(d_profit, 2),
            "total_profit": round(cur_val - (a.holding_shares * a.cost_price), 2),
            "nav_txt": "{:.4f}".format(nav),
            "holding_shares": a.holding_shares
        })

    return jsonify({
        "total_assets": round(total_val, 2),
        "total_day_profit": round(day_profit, 2),
        "funds": funds
    })

@assets_bp.route('/quotes', methods=['POST'])
def get_realtime_quotes():
    """🟢 修复 404：首页轮询实时行情接口"""
    try:
        data = request.get_json()
        codes = data.get('codes', [])
        if not codes:
            return jsonify({})

        quotes = MarketService.batch_get_valuation(codes)
        return jsonify(quotes)
    except Exception as e:
        print(f"行情刷新接口报错: {e}")
        return jsonify({}), 500

# ==========================================
# ➕ 资产添加与移动
# ==========================================

@assets_bp.route('/add', methods=['POST'])
def add_asset():
    """添加/合并资产：支持手动和 OCR 导入（生产级持久化 fund_key 版）"""
    user_id = get_current_user_id()
    data = request.get_json()
    code = data.get('fund_code')
    target_group = data.get('group_name') or DEFAULT_GROUP_NAME
    
    if not code: 
        return jsonify({"msg": "缺少代码"}), 400

    # 1. 🚀 核心改进：从蚂蚁接口获取 fund_key 和基础行情
    # 这里我们调用 Service 层的 fetch_fund_key_from_api
    fund_key = MarketService.fetch_fund_key_from_api(code)
    
    # 2. 依然获取一次行情，用于计算份额
    fund_info = MarketService.get_single_quote(code)
    fund_name = fund_info.get('name') if fund_info else data.get('name', f"未知基金{code}")
    current_nav = float(fund_info.get('nav', 1.0)) if fund_info else 1.0

    # 计算份额逻辑 (保持你原有的计算逻辑)
    if data.get('type') == 'history':
        cur_val = float(data.get('current_value', 0))
        profit = float(data.get('total_profit', 0))
        shares = cur_val / current_nav if current_nav > 0 else 0
        cost_total = cur_val - profit
    else:
        cost_total = float(data.get('investment_amount', 0))
        shares = cost_total / current_nav if current_nav > 0 else 0

    # 3. 查找现有持仓
    asset = FundAsset.query.filter_by(user_id=user_id, fund_code=code, group_name=target_group).first()
    
    try:
        if asset:
            # 合并持仓
            old_cost = asset.holding_shares * asset.cost_price
            asset.holding_shares += shares
            if asset.holding_shares > 0:
                asset.cost_price = (old_cost + cost_total) / asset.holding_shares
            asset.fund_name = fund_name
            # 🚀 补充可能缺失的 fund_key
            if fund_key: asset.fund_key = fund_key
        else:
            # 新建持仓
            new_asset = FundAsset(
                user_id=user_id, 
                fund_code=code, 
                fund_key=fund_key, # 🚀 永久存储此 Key
                fund_name=fund_name,
                holding_shares=shares, 
                cost_price=(cost_total/shares if shares > 0 else current_nav),
                group_name=target_group
            )
            db.session.add(new_asset)
        
        db.session.commit()
        return jsonify({"msg": "保存成功", "fund_key": fund_key}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"msg": f"数据库写入失败: {str(e)}"}), 500

@assets_bp.route('/move', methods=['POST'])
def move_asset():
    """移动资产到其他分组"""
    user_id = get_current_user_id()
    data = request.get_json()
    code, from_g, to_g = data.get('fund_code'), data.get('from_group'), data.get('group_name')
    
    src = FundAsset.query.filter_by(user_id=user_id, fund_code=code, group_name=from_g).first()
    dest = FundAsset.query.filter_by(user_id=user_id, fund_code=code, group_name=to_g).first()
    
    try:
        if dest and src:
            # 目标组已有，进行合并
            old_cost_total = dest.holding_shares * dest.cost_price + src.holding_shares * src.cost_price
            dest.holding_shares += src.holding_shares
            if dest.holding_shares > 0:
                dest.cost_price = old_cost_total / dest.holding_shares
            db.session.delete(src)
        elif src:
            src.group_name = to_g
        db.session.commit()
        return jsonify({"msg": "移动成功"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"msg": str(e)}), 500

# ==========================================
# 📁 分组管理接口
# ==========================================

@assets_bp.route('/groups', methods=['GET'])
def get_groups():
    user_id = get_current_user_id()
    db_groups = FundGroup.query.filter_by(user_id=user_id).order_by(FundGroup.sort_order).all()
    group_names = [g.name for g in db_groups]
    # 初始化默认账户
    if DEFAULT_GROUP_NAME not in group_names:
        default_group = FundGroup(user_id=user_id, name=DEFAULT_GROUP_NAME, sort_order=0)
        db.session.add(default_group)
        try:
            db.session.commit()
            group_names.insert(0, DEFAULT_GROUP_NAME)
        except Exception:
            db.session.rollback()

    return jsonify({"groups": [ALL_GROUP_NAME] + group_names})

@assets_bp.route('/groups/add', methods=['POST'])
def add_group():
    user_id = get_current_user_id()
    name = request.get_json().get('name')
    if not name or name in [ALL_GROUP_NAME, DEFAULT_GROUP_NAME]:
        return jsonify({"msg": "名称非法"}), 400
    if FundGroup.query.filter_by(user_id=user_id, name=name).first():
        return jsonify({"msg": "已存在"}), 400
    
    new_g = FundGroup(user_id=user_id, name=name, sort_order=99)
    db.session.add(new_g)
    db.session.commit()
    return jsonify({"msg": "成功"}), 201

@assets_bp.route('/groups/rename', methods=['POST'])
def rename_group():
    user_id = get_current_user_id()
    data = request.get_json()
    old, new = data.get('old_name'), data.get('new_name')
    group = FundGroup.query.filter_by(user_id=user_id, name=old).first()
    if not group: return jsonify({"msg": "未找到"}), 404
    
    group.name = new
    FundAsset.query.filter_by(user_id=user_id, group_name=old).update({"group_name": new})
    db.session.commit()
    return jsonify({"msg": "已重命名"}), 200

@assets_bp.route('/groups/delete', methods=['POST'])
def delete_group():
    user_id = get_current_user_id()
    name = request.get_json().get('name')
    if name == DEFAULT_GROUP_NAME: return jsonify({"msg": "默认分组不可删除"}), 400
    
    FundAsset.query.filter_by(user_id=user_id, group_name=name).delete()
    FundGroup.query.filter_by(user_id=user_id, name=name).delete()
    db.session.commit()
    return jsonify({"msg": "已删除分组及资产"}), 200

# ==========================================
# 🗑️ 删除资产
# ==========================================

@assets_bp.route('/delete/<int:id>', methods=['DELETE'])
def delete_asset(id):
    user_id = get_current_user_id()
    # 增加调试打印
    print(f"🗑️ 用户 {user_id} 请求删除资产 ID: {id}")
    
    asset = FundAsset.query.filter_by(id=id, user_id=user_id).first()
    if not asset:
        return jsonify({"msg": "资产不存在或无权限"}), 404
        
    try:
        db.session.delete(asset)
        db.session.commit()
        return jsonify({"msg": "删除成功"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"msg": str(e)}), 500