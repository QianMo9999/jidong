import requests
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import create_access_token
from ..models import db, User

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/wx-login', methods=['POST'])
def wx_login():
    code = request.json.get('code')
    appid = current_app.config['WX_APPID']
    secret = current_app.config['WX_SECRET']

    # 换取 OpenID
    url = f"https://api.weixin.qq.com/sns/jscode2session?appid={appid}&secret={secret}&js_code={code}&grant_type=authorization_code"
    wx_res = requests.get(url).json()
    openid = wx_res.get('openid')

    if not openid:
        return jsonify({"msg": "微信登录失败"}), 400

    user = User.query.filter_by(openid=openid).first()
    if not user:
        user = User(openid=openid)
        db.session.add(user)
        db.session.commit()

    token = create_access_token(identity=str(user.id))
    return jsonify(token=token)