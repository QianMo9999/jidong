from flask import Blueprint, request, jsonify
from app.services.wechat_ocr import WeChatOCRService
from ..models import db, User
import requests
import traceback

ocr_bp = Blueprint('ocr', __name__)

# ==========================================
# 🛡️ 辅助函数：通过微信 Header 获取用户 ID
# ==========================================
def get_current_user_id():
    openid = request.headers.get('x-wx-openid')
    if not openid:
        return 1  # 本地调试默认 ID
    user = User.query.filter_by(openid=openid).first()
    if not user:
        user = User(openid=openid)
        db.session.add(user)
        db.session.commit()
    return user.id

# ==========================================
# 🟢 OCR 上传识别接口 (fileID 版)
# ==========================================
@ocr_bp.route('/upload', methods=['POST'])
def upload_ocr_by_fileid():
    user_id = get_current_user_id()
    data = request.get_json()
    file_id = data.get('file_id')

    if not file_id:
        return jsonify({"msg": "缺少 file_id 参数"}), 400

    try:
        print(f"📥 用户 {user_id} 发起 OCR 请求, FileID: {file_id}")

        # 🟢 关键修正：将 process_cloud_file 改为 recognize_by_fileid
        data_list = WeChatOCRService.recognize_by_fileid(file_id)

        print(f"✅ OCR 识别成功，返回数量: {len(data_list) if data_list else 0}")
        return jsonify({"list": data_list}), 200

    except Exception as e:
        print("❌ OCR 接口发生严重错误！")
        traceback.print_exc()
        return jsonify({"msg": f"识别失败: {str(e)}"}), 500