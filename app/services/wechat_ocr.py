import requests
import json
import re
import time
import os
import io
from flask import current_app
from thefuzz import process, fuzz

class WeChatOCRService:
    _access_token = None
    _token_expire_time = 0
    _fund_map = None

    # ==========================================
    # 🛡️ 1. 基础能力：Token 与 数据加载
    # ==========================================
    @classmethod
    def get_access_token(cls):
        """获取微信 AccessToken (带缓存)"""
        if cls._access_token and time.time() < cls._token_expire_time:
            return cls._access_token
        
        appid = current_app.config.get('WX_APPID')
        secret = current_app.config.get('WX_SECRET')
        if not appid or not secret:
            raise Exception("未配置 WX_APPID 或 WX_SECRET")
            
        url = f"https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid={appid}&secret={secret}"
        res = requests.get(url, timeout=5).json()
        
        if 'access_token' in res:
            cls._access_token = res['access_token']
            cls._token_expire_time = time.time() + 7000
            return cls._access_token
        raise Exception(f"获取微信 Token 失败: {res}")

    @classmethod
    def load_fund_map(cls):
        if cls._fund_map: return cls._fund_map
        try:
            base_dir = os.path.dirname(os.path.dirname(__file__))
            path = os.path.join(base_dir, 'data', 'funds.json')
            if not os.path.exists(path): return {}
            with open(path, 'r', encoding='utf-8') as f:
                cls._fund_map = json.load(f)
            return cls._fund_map
        except: return {}

    # ==========================================
    # 📸 2. 核心识别逻辑：支持 FileID (云存储专用)
    # ==========================================
    @classmethod
    def recognize_by_fileid(cls, file_id):
        """
        🟢 新增：根据云存储 FileID 进行识别
        流程：fileID -> 临时下载 URL -> 下载图片 -> 微信 OCR
        """
        token = cls.get_access_token()
        
        # 1. 换取临时下载链接 (微信云托管内网 API)
        download_api = f"https://api.weixin.qq.com/tcb/batchdownloadfile?access_token={token}"
        payload = {
            "env": current_app.config.get('CLOUD_ENV_ID', 'prod-2gi18ont91e2bbc4'),
            "file_list": [{"fileid": file_id, "max_age": 7200}]
        }
        
        res = requests.post(download_api, json=payload, timeout=5).json()
        if res.get('errcode') != 0:
            raise Exception(f"云存储换取链接失败: {res.get('errmsg')}")
            
        file_info = res['file_list'][0]
        if file_info.get('status') != 0:
            raise Exception(f"文件状态异常: {file_info.get('errmsg')}")

        # 2. 下载图片二进制流
        img_url = file_info['download_url']
        img_resp = requests.get(img_url, timeout=10)
        
        # 3. 调用微信 OCR 识别 (复用 recognize_bytes 逻辑)
        return cls._call_wechat_ocr(img_resp.content, token)

    @classmethod
    def _call_wechat_ocr(cls, image_bytes, token):
        """统一调用微信普通 OCR 接口"""
        url = f"https://api.weixin.qq.com/cv/ocr/comm?access_token={token}"
        # 使用二进制流上传
        files = {'img': ('temp.jpg', image_bytes, 'image/jpeg')}
        response = requests.post(url, files=files, timeout=10)
        result = response.json()
        
        if result.get('errcode', 0) != 0:
             raise Exception(f"微信 OCR 接口报错: {result.get('errmsg')}")
        return cls.parse_wechat_result(result.get('items', []))

    # ==========================================
    # 🧠 3. 算法层：模糊匹配与结果解析
    # ==========================================
    @classmethod
    def get_match_score(cls, ocr_name):
        fund_map = cls.load_fund_map()
        if not fund_map: return "", 0
        clean_name = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9]', '', ocr_name)
        if len(clean_name) < 2: return "", 0 
        best_match = process.extractOne(ocr_name, fund_map.keys(), scorer=fuzz.token_sort_ratio)
        if best_match:
            matched_name, score = best_match
            return fund_map[matched_name], score
        return "", 0

    @classmethod
    def parse_wechat_result(cls, items):
        # 系统词过滤
        BLACKLIST = ['金额', '收益', '持有', '昨收', '全部', '查看', '详情', '资产', '财富号', '市场解读', '定投', '确认', '交易']
        TAIL_KEYWORDS = ['ETF', '联接', '混合', '股票', '债券', '指数', 'A', 'C', 'E']
        HEAD_KEYWORDS = ['华夏', '易方达', '南方', '嘉实', '博时', '广发', '汇添富', '富国', '招商', '天弘']

        # 1. 锚点切除
        start_index = 0
        for i, item in enumerate(items):
            txt = item['text']
            if '我的持有' in txt or ('名称' in txt and '代码' not in txt):
                start_index = i + 1
                break
        valid_items = items[start_index:] if start_index > 0 else items

        # 2. 候选行提取
        candidates = []
        current_candidate = None
        for item in valid_items:
            text = item['text'].strip()
            if len(text) < 1 or any(k in text for k in BLACKLIST): continue
            
            is_number = re.match(r'^[\+\-]?\d{1,3}(,\d{3})*(\.\d+)?%?$', text.replace('¥', ''))
            
            if is_number:
                if current_candidate:
                    try:
                        clean_num = text.replace('¥', '').replace(',', '').replace('+', '').replace('%', '')
                        current_candidate['nums'].append(float(clean_num))
                    except: pass
            else:
                if re.search(r'[¥:：>元]', text) or re.search(r'[\(\（]\d+[\)\）]', text):
                    continue
                if current_candidate: candidates.append(current_candidate)
                current_candidate = {'text': text, 'nums': [], 'code': '', 'score': 0}
        if current_candidate: candidates.append(current_candidate)

        # 3. 智能合并与清洗
        final_list = []
        for i in range(len(candidates)):
            curr = candidates[i]
            # 去除“名称”前缀干扰
            clean_name = curr['text'].replace("名称", "").strip()
            if len(clean_name) < 4: continue

            code, score = cls.get_match_score(clean_name)
            if score > 65 and len(code) == 6:
                amount = curr['nums'][0] if len(curr['nums']) >= 1 else 0
                profit = curr['nums'][1] if len(curr['nums']) >= 2 else 0
                
                if amount > 0.1:
                    final_list.append({
                        "fund_name": clean_name,
                        "fund_code": code,
                        "amount": amount,
                        "profit": profit
                    })

        return final_list