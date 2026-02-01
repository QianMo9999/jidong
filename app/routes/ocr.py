from flask import Blueprint, request, jsonify
from app.services.wechat_ocr import WeChatOCRService
from ..models import db, User
import traceback
import io

ocr_bp = Blueprint('ocr', __name__)

# ==========================================
# 🛡️ 辅助函数：通过微信 Header 获取用户 ID
# ==========================================
def get_current_user_id():
    openid = request.headers.get('x-wx-openid')
    if not openid:
        # 本地测试逻辑
        return 1
    user = User.query.filter_by(openid=openid).first()
    if not user:
        user = User(openid=openid)
        db.session.add(user)
        db.session.commit()
    return user.id

@ocr_bp.route('/upload', methods=['POST'])
def upload_ocr():
    """
    使用 multipart/form-data 方式接收文件 (配合 wx.uploadFile)
    彻底解决 callContainer 100KB 限制问题
    """
    try:
        user_id = get_current_user_id()
        
        # 🟢 1. 获取文件上传对象
        # 前端 wx.uploadFile 中的 name 参数应设为 'file'
        file = request.files.get('file')
        
        if not file:
            return jsonify({'error': '未接收到图片文件'}), 400

        # 🟢 2. 读取文件流
        # WeChatOCRService 通常需要二进制流或文件对象
        image_bytes = file.read()
        file_obj = io.BytesIO(image_bytes)

        # 🟢 3. 调用真实的 OCR 服务
        # 假设你的 WeChatOCRService 有一个识别函数
        print(f"开始为用户 {user_id} 处理 OCR 识别...")
        
        # 这里调用你真实的 OCR 逻辑
        # 示例：result = WeChatOCRService.recognize(file_obj)
        
        # 模拟返回数据（请在此处替换为你的 WeChatOCRService 调用结果）
        result = WeChatOCRService.analyze_fund_screenshot(image_bytes)
        
        if not result:
            return jsonify({'message': '未能识别有效数据', 'list': []}), 200

        return jsonify({
            'message': '识别成功',
            'list': result
        }), 200

    except Exception as e:
        print(f"OCR Error: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': 'OCR 处理失败，请检查图片清晰度'}), 500