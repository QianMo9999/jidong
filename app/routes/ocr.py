from flask import Blueprint, request, jsonify
from app.services.wechat_ocr import WeChatOCRService
from flask_jwt_extended import jwt_required
import traceback # 🟢 引入堆栈追踪库

ocr_bp = Blueprint('ocr', __name__)

@ocr_bp.route('/upload', methods=['POST'])
@jwt_required()
def upload_screenshot():
    if 'file' not in request.files:
        return jsonify({"msg": "请选择图片"}), 400
        
    file = request.files['file']
    
    try:
        # 调用 Service
        print(f"📥 收到图片上传: {file.filename}, 大小: {file.content_length}...") # 打印日志
        data = WeChatOCRService.recognize(file)
        return jsonify({"list": data}), 200
        
    except Exception as e:
        # 🟢 核心修改：把报错细节直接打印到终端！
        print("❌ OCR 接口发生严重错误！堆栈信息如下：")
        traceback.print_exc() 
        # 同时返回给前端
        return jsonify({"msg": f"服务器内部错误: {str(e)}"}), 500