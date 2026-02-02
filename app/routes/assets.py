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
    user_id = get_current_user_id()
    user_assets = FundAsset.query.filter_by(user_id=user_id).all()
    
    # 1. 现在只需传入 code 列表
    codes = [a.fund_code for a in user_assets]
    quotes = MarketService.batch_get_valuation(codes) if codes else {}
    
    results = []
    for asset in user_assets:
        quote = quotes.get(asset.fund_code) or {} # 🚀 保证 quote 不为 None
        
        shares = float(asset.holding_shares or 0)
        db_cost = float(asset.cost_price or 1.0)
        
        # 🚀 优先级：接口净值 > 接口估值 > 数据库成本价
        yest_nav = float(quote.get('nav') or quote.get('gsz') or db_cost)
        curr_gsz = float(quote.get('gsz') or yest_nav)
        gszzl = float(quote.get('gszzl') or 0.0)

        mv = shares * curr_gsz
        dp = (shares * yest_nav) * (gszzl / 100)
        tp = mv - (shares * db_cost)

        results.append({
            "id": asset.id,
            "fund_code": asset.fund_code,
            "fund_name": asset.fund_name,
            "group_name": asset.group_name or '默认账户',
            "holding_shares": round(shares, 4),
            "nav": round(yest_nav, 4),
            "gsz": round(curr_gsz, 4),
            "daily_pct": round(gszzl, 2), 
            "market_value": round(mv, 2),
            "day_profit": round(dp, 2),
            "total_profit": round(tp, 2)
        })

    return jsonify({"funds": results})

@assets_bp.route('/quotes', methods=['POST'])
def get_realtime_quotes():
    user_id = get_current_user_id()
    data = request.get_json()
    codes = data.get('codes', [])
    
    user_assets = FundAsset.query.filter_by(user_id=user_id).all()
    asset_map = {a.fund_code: a for a in user_assets}
    
    # 🚀 MarketService 内部已实现 is_exchange_traded 分流
    raw_quotes = MarketService.batch_get_valuation(codes)
    
    formatted_quotes = {}
    for code in codes:
        # 1. 拿取行情，如果该代码抓取失败，给一个空字典兜底
        q = raw_quotes.get(code) or {}
        asset = asset_map.get(code)
        
        # 2. 🚀 关键改进：多级保底提取价格
        # 场内基金接口通常返回 gsz(当前价) 和 nav(昨收)
        # 只要其中一个有值，就不能让另一个为 0
        raw_nav = float(q.get("nav") or 0)
        raw_gsz = float(q.get("gsz") or 0)
        
        # 如果 nav 是 0（比如新浪接口异常），尝试用 gsz 或数据库里的成本价顶替
        nav = raw_nav if raw_nav > 0 else (raw_gsz if raw_gsz > 0 else float(asset.cost_price or 1.0))
        # 如果 gsz 是 0（比如非交易时段），估值就等于净值
        gsz = raw_gsz if raw_gsz > 0 else nav
        
        pct = float(q.get("gszzl") or 0.0)
        
        res = {
            "nav": round(nav, 4),
            "gsz": round(gsz, 4),
            "gszzl": round(pct, 2),
            "market_value": 0,
            "day_profit": 0,
            "total_profit": 0,
            "source": q.get("source", "unknown")
        }

        # 3. 核心财务计算
        if asset:
            shares = float(asset.holding_shares or 0)
            cost = float(asset.cost_price or nav)
            
            # 市值 = 份额 * 当前估值(或现价)
            mv = shares * gsz
            # 当日收益 = (份额 * 昨日净值) * 当日涨跌幅
            # 对于场内基金，这等同于 (持仓数量 * 昨收价) * 涨幅
            dp = (shares * nav) * (pct / 100)
            # 总收益 = 当前总市值 - 总本金
            tp = mv - (shares * cost)
            
            res.update({
                "market_value": round(mv, 2),
                "day_profit": round(dp, 2),
                "total_profit": round(tp, 2)
            })
            
        formatted_quotes[code] = res

    return jsonify(formatted_quotes)

# ==========================================
# ➕ 资产添加与移动
# ==========================================

@assets_bp.route('/add', methods=['POST'])
def add_asset():
    user_id = get_current_user_id()
    data = request.get_json()
    code = data.get('fund_code', '').strip()
    target_group = data.get('group_name') or "默认账户"

    # 🚀 使用双链路逻辑获取详情
    fund_info = MarketService.get_single_quote(code)
    
    if not fund_info:
        return jsonify({"msg": "无法获取该基金详情，请检查代码是否正确"}), 404

    fund_name = fund_info.get('name')
    # 这里的 nav 在场内基金代表昨收价，在场外基金代表昨日净值
    current_nav = float(fund_info.get('nav') or 1.0)

    try:
        input_value = float(data.get('current_value') or 0)
        input_profit = float(data.get('total_profit') or 0)
    except (ValueError, TypeError):
        return jsonify({"msg": "金额格式错误"}), 400

    # 计算逻辑保持不变
    shares = round(input_value / current_nav, 4)
    cost_total = input_value - input_profit
    avg_cost_price = cost_total / shares if shares > 0 else current_nav

    # 3. 合并或新建逻辑
    asset = FundAsset.query.filter_by(user_id=user_id, fund_code=code, group_name=target_group).first()
    
    try:
        if asset:
            old_shares = float(asset.holding_shares or 0)
            old_cost_price = float(asset.cost_price or current_nav)
            new_total_shares = old_shares + shares
            if new_total_shares > 0:
                asset.cost_price = (old_shares * old_cost_price + cost_total) / new_total_shares
                asset.holding_shares = new_total_shares
            asset.fund_name = fund_name
        else:
            new_asset = FundAsset(
                user_id=user_id, 
                fund_code=code, 
                fund_name=fund_name,
                holding_shares=shares, 
                cost_price=avg_cost_price,
                group_name=target_group,
                fund_key=None # 🚀 彻底弃用这个字段
            )
            db.session.add(new_asset)
        
        db.session.commit()
        return jsonify({"msg": f"【{fund_name}】保存成功", "shares": shares}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"msg": f"保存失败: {str(e)}"}), 500

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