import requests
from flask import Blueprint, request, jsonify
from flask_jwt_extended import create_access_token
from ..models import db, User

auth_bp = Blueprint('auth', __name__)

# app/routes/auth.py
@auth_bp.route('/login', methods=['POST'])
def login():
    openid = request.headers.get('x-wx-openid')
    if not openid:
        return jsonify({"msg": "请在微信环境访问"}), 401
    
    user = User.query.filter_by(openid=openid).first()
    if not user:
        user = User(openid=openid)
        db.session.add(user)
        db.session.commit()
    
    return jsonify({"msg": "登录成功", "openid": openid})