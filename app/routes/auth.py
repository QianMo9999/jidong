import requests
from flask import Blueprint, request, jsonify
from flask_jwt_extended import create_access_token
from ..models import db, User

auth_bp = Blueprint('auth', __name__)

# app/routes/auth.py
@auth_bp.route('/login', methods=['POST'])
def wx_login():
    # 🟢 微信云托管会自动注入这个 Header
    openid = request.headers.get('x-wx-openid')
    
    if not openid:
        return jsonify({"msg": "未获取到用户信息，请在微信环境访问"}), 401

    # 查找或创建用户
    user = User.query.filter_by(openid=openid).first()
    if not user:
        user = User(openid=openid)
        db.session.add(user)
        db.session.commit()

    # 签发 JWT Token
    access_token = create_access_token(identity=str(user.id))
    return jsonify({"token": access_token})