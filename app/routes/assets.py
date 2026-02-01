from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from ..models import db, FundAsset, FundGroup
from ..services.market import MarketService

assets_bp = Blueprint('assets', __name__)

# 系统常量
DEFAULT_GROUP_NAME = '默认账户'
ALL_GROUP_NAME = '全部'

# ==========================================
# 🟢 1. 获取分组列表
# ==========================================
@assets_bp.route('/groups', methods=['GET'])
@jwt_required()
def get_groups():
    user_id = get_jwt_identity()
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
@jwt_required()
def add_group():
    user_id = get_jwt_identity()
    data = request.get_json()
    name = data.get('name')
    
    if not name: 
        return jsonify({"msg": "名称不能为空"}), 400
    
    # 防止用户通过接口创建叫“全部”的分组，这会影响前端逻辑
    if name == ALL_GROUP_NAME: 
        return jsonify({"msg": "系统保留名称，无法创建"}), 400
        
    # 检查当前用户是否已有同名分组
    if FundGroup.query.filter_by(user_id=user_id, name=name).first():
        return jsonify({"msg": "分组已存在"}), 400
        
    # 计算当前分组数量，作为排序权重
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
# 🟢 3. 添加资产 (修复版：支持断网强制保存 + OCR名字兜底)
# ==========================================
@assets_bp.route('/add', methods=['POST'])
@jwt_required()
def add_asset():
    user_id = get_jwt_identity()
    data = request.get_json()
    
    # 1. 获取参数
    code = data.get('fund_code')
    add_type = data.get('type') 
    target_group = data.get('group_name') or DEFAULT_GROUP_NAME
    
    # 🟢 关键：获取前端 OCR 识别到的名字 (救命稻草)
    request_name = data.get('name')
    
    if not code:
        return jsonify({"msg": "缺少基金代码"}), 400

    # 2. 尝试获取行情 (可能会失败返回 None)
    fund_info = MarketService.get_fund_data(code)
    if fund_info == None: print("fund_info:None")
    else: print("fund_info:", fund_info)
    
    # =======================================================
    # 🚨 核心修复：查不到行情时，启用强制保存模式 (兜底逻辑)
    # =======================================================
    if not fund_info:
        print(f"⚠️ 警告：无法获取 {code} 的行情，使用兜底模式保存")
        
        # 优先使用前端传来的 OCR 名字，如果没有就叫 "未知基金"
        fallback_name = request_name if request_name else f"未知基金{code}"
        
        # 构造假数据，保证流程能走下去
        fund_info = {
            "name": fallback_name,
            "nav": 1.0,  # 默认净值 1.0，防止除以 0
            "daily_pct": 0.0,
            "update_time": ""
        }

    # 3. 确定最终使用的名字和净值
    fund_name = fund_info.get('name')
    # print(fund_info)
    # 双重保险：如果接口返回了 info 但 name 是空的，或者叫未知基金，尝试用 OCR 名字覆盖
    if (not fund_name or "未知基金" in fund_name) and request_name:
        fund_name = request_name

    current_nav = float(fund_info.get('nav', 0))
    # 防止净值为 0 或负数导致计算错误
    if current_nav <= 0: 
        current_nav = 1.0

    # 4. 计算份额和成本
    new_shares = 0.0
    new_cost_total = 0.0
    
    if add_type == 'history':
        # --- 历史持仓导入模式 ---
        # 前端传入：当前市值 (current_value), 总收益 (total_profit)
        current_value = float(data.get('current_value', 0))
        total_profit = float(data.get('total_profit', 0))
        
        # 反推总成本 = 市值 - 利润
        new_cost_total = current_value - total_profit
        
        # 反推份额 = 市值 / 当前净值
        new_shares = current_value / current_nav
    else:
        # --- 普通买入模式 ---
        # 前端传入：投入金额 (investment_amount)
        new_cost_total = float(data.get('investment_amount', 0))
        
        # 计算份额 = 投入 / 当前净值 (简化计算，暂不扣除费率)
        new_shares = new_cost_total / current_nav

    # 5. 数据库操作
    existing_asset = FundAsset.query.filter_by(
        user_id=user_id, 
        fund_code=code, 
        group_name=target_group 
    ).first()

    try:
        if existing_asset:
            # === 合并逻辑 ===
            # 计算旧的总成本 (旧份额 * 旧成本价)
            old_cost_total = existing_asset.holding_shares * existing_asset.cost_price
            
            # 累加份额和成本
            total_shares = existing_asset.holding_shares + new_shares
            total_cost = old_cost_total + new_cost_total
            
            # 更新字段
            existing_asset.holding_shares = total_shares
            existing_asset.fund_name = fund_name # 顺便更新名字（万一之前是未知的）
            
            # 重新计算平均成本价
            if total_shares > 0:
                existing_asset.cost_price = total_cost / total_shares
            
            msg = f"已合并至 [{target_group}]"
        else:
            # === 新建逻辑 ===
            # 计算初始成本价
            calc_cost_price = 0.0
            if new_shares > 0:
                calc_cost_price = new_cost_total / new_shares
            else:
                calc_cost_price = current_nav # 兜底值
            
            new_asset = FundAsset(
                user_id=user_id,
                fund_code=code,
                fund_name=fund_name,
                holding_shares=new_shares,
                cost_price=calc_cost_price,
                group_name=target_group
            )
            db.session.add(new_asset)
            msg = "添加成功"
        
        db.session.commit()
        # 返回 fund_name 方便前端展示
        return jsonify({"msg": msg, "name": fund_name}), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"msg": f"数据保存失败: {str(e)}"}), 500

# ==========================================
# 🟢 4. 移动资产 (修复合并逻辑)
# ==========================================
@assets_bp.route('/move', methods=['POST'])
@jwt_required()
def move_asset():
    user_id = get_jwt_identity()
    data = request.get_json()
    
    fund_code = data.get('fund_code')
    from_group = data.get('from_group')
    to_group = data.get('group_name')
    
    if not all([fund_code, from_group, to_group]):
        return jsonify({"msg": "参数缺失"}), 400
        
    if to_group == ALL_GROUP_NAME:
        return jsonify({"msg": "不能移动到系统虚拟分组"}), 400

    src_asset = FundAsset.query.filter_by(user_id=user_id, fund_code=fund_code, group_name=from_group).first()
    if not src_asset: return jsonify({"msg": "源资产不存在"}), 404
        
    target_asset = FundAsset.query.filter_by(user_id=user_id, fund_code=fund_code, group_name=to_group).first()
    
    try:
        if target_asset:
            src_total_cost = src_asset.holding_shares * src_asset.cost_price
            tgt_total_cost = target_asset.holding_shares * target_asset.cost_price
            new_shares = target_asset.holding_shares + src_asset.holding_shares
            target_asset.holding_shares = new_shares
            if new_shares > 0:
                target_asset.cost_price = (src_total_cost + tgt_total_cost) / new_shares
            db.session.delete(src_asset)
        else:
            src_asset.group_name = to_group
            
        db.session.commit()
        return jsonify({"msg": "移动成功"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"msg": str(e)}), 500

# ==========================================
# 🟢 5. 获取资产列表
# ==========================================
@assets_bp.route('/list', methods=['GET'])
@jwt_required()
def list_assets():
    user_id = get_jwt_identity()
    assets = FundAsset.query.filter_by(user_id=user_id).all()
    
    total_val = 0
    day_profit = 0
    funds = []

    for a in assets:
        mkt = MarketService.get_fund_data(a.fund_code)
        nav = float(mkt.get('nav', 1.0)) if mkt else 1.0
        daily_pct = float(mkt.get('daily_pct', 0.0)) if mkt else 0.0
        
        cur_val = a.holding_shares * nav
        d_profit = (cur_val / (1 + daily_pct/100)) * (daily_pct/100)
        
        total_val += cur_val
        day_profit += d_profit

        funds.append({
            "id": a.id,
            "fund_name": a.fund_name,
            "fund_code": a.fund_code,
            "group_name": a.group_name, # 🟢 返回 group_name
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
# 🟢 6. 其他接口 (删除、分组管理)
# ==========================================
@assets_bp.route('/delete/<int:id>', methods=['DELETE'])
@jwt_required()
def delete_asset(id):
    user_id = get_jwt_identity()
    
    # 🟢 获取可选参数 deleteAll
    delete_all = request.args.get('all') == 'true'
    
    # 先找到当前这条资产
    asset = FundAsset.query.filter_by(id=id, user_id=user_id).first()
    if not asset:
        return jsonify({"msg": "资产不存在"}), 404
    
    try:
        if delete_all:
            # 🟢 核心逻辑：删除该用户下所有分组中的这只基金
            FundAsset.query.filter_by(user_id=user_id, fund_code=asset.fund_code).delete()
            msg = f"已清空所有分组中的 {asset.fund_name}"
        else:
            # 只删除当前单条记录
            db.session.delete(asset)
            msg = "删除成功"
            
        db.session.commit()
        return jsonify({"msg": msg}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"msg": str(e)}), 500

# ==========================================
# 🟢 7. 分组重命名 (需同步更新资产表中的 group_name)
# ==========================================
@assets_bp.route('/groups/rename', methods=['POST'])
@jwt_required()
def rename_group():
    user_id = get_jwt_identity()
    data = request.get_json()
    old_name = data.get('old_name')
    new_name = data.get('new_name')
    
    if not new_name: return jsonify({"msg": "新名称不能为空"}), 400
    if old_name in [ALL_GROUP_NAME, DEFAULT_GROUP_NAME]:
        return jsonify({"msg": "系统分组不可重命名"}), 400
        
    # 查找原分组
    group = FundGroup.query.filter_by(user_id=user_id, name=old_name).first()
    if not group: return jsonify({"msg": "原分组不存在"}), 404
    
    try:
        # 1. 更新分组表名称
        group.name = new_name
        
        # 2. 🟢 关键：同步更新该分组下所有资产的 group_name
        FundAsset.query.filter_by(user_id=user_id, group_name=old_name).update({"group_name": new_name})
        
        db.session.commit()
        return jsonify({"msg": "重命名成功"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"msg": str(e)}), 500

# ==========================================
# 🟢 8. 删除分组 (同时删除其下所有基金)
# ==========================================
@assets_bp.route('/groups/delete', methods=['POST'])
@jwt_required()
def delete_group():
    user_id = get_jwt_identity()
    data = request.get_json()
    name = data.get('name')
    
    if name in [ALL_GROUP_NAME, DEFAULT_GROUP_NAME]:
        return jsonify({"msg": "无法删除系统默认分组"}), 400
        
    group = FundGroup.query.filter_by(user_id=user_id, name=name).first()
    if not group: return jsonify({"msg": "分组不存在"}), 404
        
    try:
        # 🟢 核心改动：不再转移，而是直接删除该分组下的所有资产
        FundAsset.query.filter_by(user_id=user_id, group_name=name).delete()
        
        # 删除分组本身
        db.session.delete(group)
        
        db.session.commit()
        return jsonify({"msg": f"分组 '{name}' 及其下资产已全部删除"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"msg": str(e)}), 500
    
@assets_bp.route('/quotes', methods=['POST'])
@jwt_required()
def get_realtime_quotes():
    data = request.get_json()
    codes = data.get('codes', [])
    
    if not codes:
        return jsonify({})
    
    # 调用批量抓取
    quotes = MarketService.batch_get_valuation(codes)
    return jsonify(quotes)