import requests
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import create_access_token
from ..models import db, User

auth_bp = Blueprint('auth', __name__)

# app/routes/auth.py

@auth_bp.route('/login', methods=['POST'])
def wx_login():
    # 🟢 直接从微信网关注入的 Header 中获取 OpenID
    openid = request.headers.get('x-wx-openid')
    
    if not openid:
        # 如果是本地调试（没有网关注入），可以留一个兜底或者报错
        return jsonify({"msg": "请在微信环境内访问"}), 401

    # 1. 查找或创建用户
    user = User.query.filter_by(openid=openid).first()
    if not user:
        user = User(openid=openid)
        db.session.add(user)
        db.session.commit()

    # 2. 生成你自己的 JWT Token 返回给前端
    access_token = create_access_token(identity=str(user.id))
    return jsonify({"token": access_token, "msg": "登录成功"})