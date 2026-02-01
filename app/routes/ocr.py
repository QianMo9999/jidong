from flask import Blueprint, request, jsonify
from app.services.wechat_ocr import WeChatOCRService
from flask_jwt_extended import jwt_required
import traceback # 🟢 引入堆栈追踪库
import base64
import io

ocr_bp = Blueprint('ocr', __name__)

ocr_bp = Blueprint('ocr', __name__)

@ocr_bp.route('/upload', methods=['POST'])
@jwt_required() # 如果你需要鉴权就打开
def upload_ocr():
    try:
        # 🟢 1. 获取 JSON 数据
        data = request.get_json()
        if not data or 'image_base64' not in data:
            return jsonify({'error': 'No image data provided'}), 400

        # 🟢 2. 解码 Base64
        image_base64 = data['image_base64']
        
        # 将 base64 字符串转回二进制数据
        image_bytes = base64.b64decode(image_base64)
        
        # 🟢 3. 处理图片
        # 如果你的 OCR 服务需要文件对象，用 io.BytesIO 包装一下
        # 它的行为就像一个打开的文件一样
        file_obj = io.BytesIO(image_bytes)
        
        # === 调用你的 OCR 逻辑 ===
        # 假设你的 OCR 函数原本接收 file 对象：
        # result = OCRService.process(file_obj)
        
        # 这里的 result 是模拟的返回数据
        # 实际代码请替换为你真实的 OCR 调用
        result = [
            {"fund_code": "001234", "amount": 1000},
            {"fund_code": "005678", "amount": 2000}
        ]
        
        return jsonify({'message': 'Success', 'list': result}), 200

    except Exception as e:
        print(f"OCR Error: {e}")
        return jsonify({'error': str(e)}), 500