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
    
    # 1. 构造请求项
    fund_items = [{'code': a.fund_code, 'key': a.fund_key} for a in user_assets]
    
    # 2. 获取实时行情
    quotes = MarketService.batch_get_valuation(fund_items) if fund_items else {}
    
    results = []
    needs_commit = False # 标记是否需要回写数据库

    for asset in user_assets:
        quote = quotes.get(asset.fund_code)
        
        # 1. 基础数据准备
        shares = float(asset.holding_shares or 0)
        db_cost = float(asset.cost_price or 0)
        
        # 2. 确定“昨日参考价” (yest_nav)
        yest_nav = float(quote.get('nav', db_cost)) if quote else db_cost
        
        # 3. 确定“当前估值价” (curr_gsz) 和 “当日涨幅” (gszzl)
        curr_gsz = float(quote.get('gsz', yest_nav)) if quote else yest_nav
        gszzl = float(quote.get('gszzl', 0.0)) if quote else 0.0

        # 4. 财务核心计算
        mv = shares * curr_gsz
        dp = (shares * yest_nav) * (gszzl / 100)
        tp = mv - (shares * db_cost) if db_cost > 0 else 0

        # 5. 组装返回给前端的数据 (严格控制小数位数)
        results.append({
            "id": asset.id,
            "fund_code": asset.fund_code,
            "fund_name": asset.fund_name,
            "group_name": asset.group_name or '默认账户',
            "holding_shares": shares,
            # 🚀 单价类保留 4 位小数
            "nav": round(yest_nav, 4),          
            "gsz": round(curr_gsz, 4),          
            # 🚀 涨幅与金额类保留 2 位小数
            "daily_pct": round(gszzl, 2),       
            "market_value": round(mv, 2),  
            "day_profit": round(dp, 2),
            "total_profit": round(tp, 2),
            "source": quote.get('source', 'cache') if quote else 'db'
        })

    # 如果补全了 key，执行一次提交，下次刷新就直接飞快了
    if needs_commit:
        try:
            db.session.commit()
        except:
            db.session.rollback()

    # 🚀 包装在 funds 对象中返回，匹配前端 res.funds
    return jsonify({"funds": results})

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
    """统一资产添加逻辑：不论来源，一律按 NAV 折算份额并持久化"""
    user_id = get_current_user_id()
    data = request.get_json()
    code = data.get('fund_code')
    target_group = data.get('group_name') or "默认账户"
    
    if not code: 
        return jsonify({"msg": "缺少代码"}), 400

    # 1. 获取接口确定的最新 NAV
    fund_info = MarketService.get_single_quote(code)
    if not fund_info:
        return jsonify({"msg": "获取行情失败"}), 500

    # 核心字段提取
    fund_key = fund_info.get('fund_key')
    fund_name = fund_info.get('name') or data.get('name', f"基金{code}")
    current_nav = float(fund_info.get('nav', 1.0)) # 自动更新的最新收盘净值

    # 2. 统一计算逻辑 (不再区分 type)
    # 用户上传的“当前持仓金额”
    current_value = float(data.get('current_value') or data.get('investment_amount') or 0)
    # 用户上传的“总收益”（如果没有传，则默认本金=当前市值，即初始盈亏为0）
    total_profit = float(data.get('total_profit', 0))
    
    # 计算本金和份额
    # 份额 = 当前市值 / 确定的 NAV
    shares = current_value / current_nav if current_nav > 0 else 0
    # 投入本金 = 当前市值 - 累计收益
    cost_total = current_value - total_profit

    # 3. 查找并更新持仓
    asset = FundAsset.query.filter_by(user_id=user_id, fund_code=code, group_name=target_group).first()
    
    try:
        if asset:
            # 合并持仓：累加份额，重新计算平均成本
            old_cost_sum = asset.holding_shares * asset.cost_price
            asset.holding_shares += shares
            if asset.holding_shares > 0:
                asset.cost_price = (old_cost_sum + cost_total) / asset.holding_shares
            asset.fund_name = fund_name
            if fund_key: asset.fund_key = fund_key
        else:
            # 新建持仓
            new_asset = FundAsset(
                user_id=user_id, 
                fund_code=code, 
                fund_key=fund_key,
                fund_name=fund_name,
                holding_shares=shares, 
                # 初始平均成本价
                cost_price=(cost_total / shares if shares > 0 else current_nav),
                group_name=target_group
            )
            db.session.add(new_asset)
        
        db.session.commit()
        return jsonify({"msg": "保存成功", "shares": round(shares, 4)}), 201

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