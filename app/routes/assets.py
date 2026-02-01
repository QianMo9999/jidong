from flask import Blueprint, request, jsonify
from ..models import db, FundAsset, FundGroup, User  # 导入 User 模型
from ..services.market import MarketService

assets_bp = Blueprint('assets', __name__)

# 系统常量
DEFAULT_GROUP_NAME = '默认账户'
ALL_GROUP_NAME = '全部'

# ==========================================
# 🛡️ 辅助函数：通过微信 Header 获取用户 ID
# ==========================================
def get_current_user_id():
    """
    从微信云托管注入的 Header 中获取 OpenID，并映射为数据库 user_id
    """
    # 微信云托管会自动注入 x-wx-openid
    openid = request.headers.get('x-wx-openid')
    
    # 🟢 本地开发兼容：如果没有 Header，说明是本地调试，返回 ID 为 1 的用户
    if not openid:
        print("⚠️ 未获取到 x-wx-openid，正在使用本地调试模式 (User ID: 1)")
        return 1
    
    # 查表获取 ID
    user = User.query.filter_by(openid=openid).first()
    if not user:
        # 如果用户不存在（比如第一次访问），自动创建
        user = User(openid=openid)
        db.session.add(user)
        db.session.commit()
        
    return user.id

# ==========================================
# 🟢 1. 获取分组列表
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

# ==========================================
# 🟢 2. 添加分组
# ==========================================
@assets_bp.route('/groups/add', methods=['POST'])
def add_group():
    user_id = get_current_user_id()
    data = request.get_json()
    name = data.get('name')
    
    if not name: 
        return jsonify({"msg": "名称不能为空"}), 400
    if name == ALL_GROUP_NAME: 
        return jsonify({"msg": "系统保留名称"}), 400
        
    if FundGroup.query.filter_by(user_id=user_id, name=name).first():
        return jsonify({"msg": "分组已存在"}), 400
        
    count = FundGroup.query.filter_by(user_id=user_id).count()
    new_group = FundGroup(user_id=user_id, name=name, sort_order=count)
    
    try:
        db.session.add(new_group)
        db.session.commit()
        return jsonify({"msg": "创建成功"}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"msg": f"创建失败: {str(e)}"}), 500

# ==========================================
# 🟢 3. 添加资产
# ==========================================
@assets_bp.route('/add', methods=['POST'])
def add_asset():
    user_id = get_current_user_id()
    data = request.get_json()
    
    code = data.get('fund_code')
    add_type = data.get('type') 
    target_group = data.get('group_name') or DEFAULT_GROUP_NAME
    request_name = data.get('name')
    
    if not code:
        return jsonify({"msg": "缺少基金代码"}), 400

    fund_info = MarketService.get_fund_data(code)
    
    # 兜底逻辑：无行情时强制保存
    if not fund_info:
        fallback_name = request_name if request_name else f"未知基金{code}"
        fund_info = {"name": fallback_name, "nav": 1.0, "daily_pct": 0.0}

    fund_name = fund_info.get('name')
    if (not fund_name or "未知基金" in fund_name) and request_name:
        fund_name = request_name

    current_nav = float(fund_info.get('nav', 1.0))
    if current_nav <= 0: current_nav = 1.0

    # 计算份额和成本
    new_shares = 0.0
    new_cost_total = 0.0
    
    if add_type == 'history':
        current_value = float(data.get('current_value', 0))
        total_profit = float(data.get('total_profit', 0))
        new_cost_total = current_value - total_profit
        new_shares = current_value / current_nav
    else:
        new_cost_total = float(data.get('investment_amount', 0))
        new_shares = new_cost_total / current_nav

    existing_asset = FundAsset.query.filter_by(
        user_id=user_id, fund_code=code, group_name=target_group 
    ).first()

    try:
        if existing_asset:
            old_cost_total = existing_asset.holding_shares * existing_asset.cost_price
            total_shares = existing_asset.holding_shares + new_shares
            total_cost = old_cost_total + new_cost_total
            existing_asset.holding_shares = total_shares
            existing_asset.fund_name = fund_name
            if total_shares > 0:
                existing_asset.cost_price = total_cost / total_shares
            msg = f"已合并至 [{target_group}]"
        else:
            calc_cost_price = new_cost_total / new_shares if new_shares > 0 else current_nav
            new_asset = FundAsset(
                user_id=user_id, fund_code=code, fund_name=fund_name,
                holding_shares=new_shares, cost_price=calc_cost_price,
                group_name=target_group
            )
            db.session.add(new_asset)
            msg = "添加成功"
        
        db.session.commit()
        return jsonify({"msg": msg, "name": fund_name}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"msg": str(e)}), 500

# ==========================================
# 🟢 4. 获取资产列表
# ==========================================
@assets_bp.route('/list', methods=['GET'])
def list_assets():
    user_id = get_current_user_id()
    assets = FundAsset.query.filter_by(user_id=user_id).all()
    
    # 提取所有基金代码，准备批量查询（优化性能）
    codes = [a.fund_code for a in assets]
    quotes = MarketService.batch_get_valuation(codes) if codes else {}
    
    total_val = 0
    day_profit = 0
    funds = []

    for a in assets:
        # 从批量查询结果中获取行情，无结果则用默认值
        mkt = quotes.get(a.fund_code, {})
        nav = float(mkt.get('nav', 1.0))
        daily_pct = float(mkt.get('daily_pct', 0.0))
        
        cur_val = a.holding_shares * nav
        # 估算当日收益
        d_profit = (cur_val / (1 + daily_pct/100)) * (daily_pct/100)
        
        total_val += cur_val
        day_profit += d_profit

        funds.append({
            "id": a.id,
            "fund_name": a.fund_name,
            "fund_code": a.fund_code,
            "group_name": a.group_name,
            "market_value": "{:.2f}".format(cur_val),
            "current_nav": nav,
            "daily_pct": daily_pct,
            "day_profit": round(d_profit, 2),
            "total_profit": round(cur_val - (a.holding_shares * a.cost_price), 2),
            "nav_txt": "{:.4f}".format(nav), 
        })

    return jsonify({
        "total_assets": round(total_val, 2),
        "total_day_profit": round(day_profit, 2),
        "funds": funds
    })

# ==========================================
# 🟢 5. 移动资产
# ==========================================
@assets_bp.route('/move', methods=['POST'])
def move_asset():
    user_id = get_current_user_id()
    data = request.get_json()
    fund_code, from_group, to_group = data.get('fund_code'), data.get('from_group'), data.get('group_name')
    
    if not all([fund_code, from_group, to_group]): return jsonify({"msg": "参数缺失"}), 400
    if to_group == ALL_GROUP_NAME: return jsonify({"msg": "非法操作"}), 400

    src_asset = FundAsset.query.filter_by(user_id=user_id, fund_code=fund_code, group_name=from_group).first()
    target_asset = FundAsset.query.filter_by(user_id=user_id, fund_code=fund_code, group_name=to_group).first()
    
    try:
        if target_asset and src_asset:
            new_shares = target_asset.holding_shares + src_asset.holding_shares
            if new_shares > 0:
                target_asset.cost_price = ((src_asset.holding_shares * src_asset.cost_price) + 
                                          (target_asset.holding_shares * target_asset.cost_price)) / new_shares
            target_asset.holding_shares = new_shares
            db.session.delete(src_asset)
        elif src_asset:
            src_asset.group_name = to_group
            
        db.session.commit()
        return jsonify({"msg": "移动成功"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"msg": str(e)}), 500

# ==========================================
# 🟢 6. 删除资产/分组管理 (其余逻辑保持一致，仅更换 user_id 获取方式)
# ==========================================
@assets_bp.route('/delete/<int:id>', methods=['DELETE'])
def delete_asset(id):
    user_id = get_current_user_id()
    delete_all = request.args.get('all') == 'true'
    asset = FundAsset.query.filter_by(id=id, user_id=user_id).first()
    if not asset: return jsonify({"msg": "资产不存在"}), 404
    
    try:
        if delete_all:
            FundAsset.query.filter_by(user_id=user_id, fund_code=asset.fund_code).delete()
        else:
            db.session.delete(asset)
        db.session.commit()
        return jsonify({"msg": "操作成功"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"msg": str(e)}), 500

@assets_bp.route('/groups/rename', methods=['POST'])
def rename_group():
    user_id = get_current_user_id()
    data = request.get_json()
    old_name, new_name = data.get('old_name'), data.get('new_name')
    group = FundGroup.query.filter_by(user_id=user_id, name=old_name).first()
    if not group: return jsonify({"msg": "分组不存在"}), 404
    
    try:
        group.name = new_name
        FundAsset.query.filter_by(user_id=user_id, group_name=old_name).update({"group_name": new_name})
        db.session.commit()
        return jsonify({"msg": "成功"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"msg": str(e)}), 500

@assets_bp.route('/groups/delete', methods=['POST'])
def delete_group():
    user_id = get_current_user_id()
    name = request.get_json().get('name')
    group = FundGroup.query.filter_by(user_id=user_id, name=name).first()
    if not group: return jsonify({"msg": "分组不存在"}), 404
    try:
        FundAsset.query.filter_by(user_id=user_id, group_name=name).delete()
        db.session.delete(group)
        db.session.commit()
        return jsonify({"msg": "删除成功"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"msg": str(e)}), 500