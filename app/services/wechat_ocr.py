import requests
import json
import re
import time
import os
from flask import current_app
from thefuzz import process, fuzz

class WeChatOCRService:
    _access_token = None
    _token_expire_time = 0
    _fund_map = None

    @classmethod
    def get_access_token(cls):
        if cls._access_token and time.time() < cls._token_expire_time:
            return cls._access_token
        appid = current_app.config.get('WX_APPID')
        secret = current_app.config.get('WX_SECRET')
        if not appid or not secret: raise Exception("未配置 WX_APPID")
        url = f"https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid={appid}&secret={secret}"
        res = requests.get(url).json()
        if 'access_token' in res:
            cls._access_token = res['access_token']
            cls._token_expire_time = time.time() + 7000
            return cls._access_token
        raise Exception(f"Token Error: {res}")

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
    def recognize(cls, image_file):
        image_file.seek(0)
        token = cls.get_access_token()
        url = f"https://api.weixin.qq.com/cv/ocr/comm?access_token={token}"
        files = {'img': (image_file.filename, image_file.read(), image_file.content_type)}
        response = requests.post(url, files=files)
        result = response.json()
        if result.get('errcode', 0) != 0:
             raise Exception(f"微信OCR接口报错: {result.get('errmsg')}")
        return cls.parse_wechat_result(result.get('items', []))

    @classmethod
    def parse_wechat_result(cls, items):
        # 1. 垃圾词黑名单 (过滤无关行)
        BLACKLIST = [
            '金额', '收益', '持有', '昨收', '全部', '查看', '详情', '资产',
            '财富号', '市场解读', '定投', '金选', '排序', '组合', '大盘',
            '买入', '卖出', '费率', '确认', '交易', '规则', '档案', '讨论',
            '最新', '净值', '估值', '周涨', '分析', '记录', '计划', '保障', 
            '理财师', '明细', '加薪', '榜单', '眼', '偏股', '偏债', '指数'
        ]

        TAIL_KEYWORDS = ['ETF', '联接', '混合', '股票', '债券', '指数', 'A', 'C', 'E', '发起式']
        HEAD_KEYWORDS = [
            '华夏', '易方达', '南方', '嘉实', '博时', '广发', '汇添富', 
            '富国', '招商', '鹏华', '工银', '景顺', '中欧', '天弘', 
            '永赢', '前海', '兴全', '兴证', '银华', '交银', '华安'
        ]

        # 🟢 策略1：锚点定位 (切除头部总金额区域)
        # 寻找“列表开始”的标志，通常是“我的持有”或者表头“名称”
        start_index = 0
        for i, item in enumerate(items):
            txt = item['text']
            # 如果出现这些词，说明正文列表从这之后开始
            if '我的持有' in txt or ('名称' in txt and '代码' not in txt):
                start_index = i + 1 # 从下一行开始
                break
        
        # 只保留锚点之后的数据
        valid_items = items[start_index:] if start_index > 0 else items

        candidates = []
        current_candidate = None

        # --- 预处理 ---
        for item in valid_items:
            text = item['text'].strip()
            
            # 跳过空行或黑名单
            if len(text) < 1: continue
            if any(k in text for k in BLACKLIST): continue

            # 🟢 策略2：字符级过滤 (排除带特殊符号的行)
            # 正常基金名不含：¥, :, ：, >, 元 (除非是数字行)
            is_number = re.match(r'^[\+\-]?\d{1,3}(,\d{3})*(\.\d+)?%?$', text.replace('¥', ''))
            
            if not is_number:
                # 如果不是数字，且包含非法字符，直接丢弃
                if re.search(r'[¥:：>元]', text):
                    continue
                # 排除像 "股票型(0)" 这种分类标签
                if re.search(r'[\(\（]\d+[\)\）]', text):
                    continue

            if is_number:
                if current_candidate:
                    clean_num = text.replace('¥', '').replace(',', '').replace('+', '').replace('%', '')
                    try:
                        val = float(clean_num)
                        current_candidate['nums'].append(val)
                    except: pass
            else:
                if current_candidate: candidates.append(current_candidate)
                current_candidate = {
                    'text': text,
                    'nums': [],
                    'code': '',
                    'score': 0
                }
        if current_candidate: candidates.append(current_candidate)

        # --- 智能合并 (逻辑保持不变，因为之前调得挺好) ---
        merged_candidates = []
        skip_next = False

        for i in range(len(candidates)):
            if skip_next:
                skip_next = False
                continue

            curr = candidates[i]
            
            if i < len(candidates) - 1:
                next_item = candidates[i+1]
                
                should_merge = False
                
                code1, score1 = cls.get_match_score(curr['text'])
                code2, score2 = cls.get_match_score(next_item['text'])
                code_merged, score_merged = cls.get_match_score(curr['text'] + next_item['text'])

                # 刹车逻辑
                if any(next_item['text'].startswith(k) for k in HEAD_KEYWORDS):
                    should_merge = False
                elif score1 > 90 and score2 > 80:
                    should_merge = False
                
                # 推进逻辑
                elif len(next_item['text']) <= 4:
                    should_merge = True
                elif any(k in next_item['text'] for k in TAIL_KEYWORDS):
                    if len(next_item['text']) < 8 or score_merged > score1:
                        should_merge = True
                elif score_merged > score1 + 15:
                     should_merge = True

                if should_merge:
                    curr['text'] += next_item['text']
                    curr['nums'].extend(next_item['nums'])
                    curr['code'] = code_merged
                    curr['score'] = score_merged
                    skip_next = True
                else:
                    curr['code'] = code1
                    curr['score'] = score1
            else:
                code, score = cls.get_match_score(curr['text'])
                curr['code'] = code
                curr['score'] = score
            
            merged_candidates.append(curr)

        # ... (前面的逻辑保持不变)

        # --- 3. 最终清洗 ---
        final_list = []
        for cand in merged_candidates:
            # 🟢 1. 核心修复：去除 "名称" 前缀
            # 有时候 OCR 会把 "名称" 和 基金名 连在一起识别
            clean_name = cand['text'].replace("名称", "").strip()

            # 🟢 2. 重新检查长度
            # 如果去掉 "名称" 后只剩下空字符串或 1 个字，说明这行本身就是表头，直接丢弃
            if len(clean_name) < 4: 
                continue

            # 3. 检查代码 (必须是 6 位)
            if not cand['code'] or len(cand['code']) != 6: 
                continue
            
            amount = 0
            profit = 0
            if cand['nums']:
                if len(cand['nums']) >= 1: amount = cand['nums'][0]
                if len(cand['nums']) >= 2: profit = cand['nums'][1]

            if amount <= 0.01:
                continue

            final_list.append({
                "fund_name": clean_name, # 🟢 使用清洗后的名字
                "fund_code": cand['code'],
                "amount": amount,
                "profit": profit
            })

        return final_list