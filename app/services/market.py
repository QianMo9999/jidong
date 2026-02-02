import re
import time
import json
import requests
import redis
import urllib3
from flask import current_app, has_app_context

# 禁用 SSL 警告（配合你之前的 verify=False 策略）
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class MarketService:
    @staticmethod
    def get_redis():
        """
        🟢 防御性获取 Redis 实例
        通过 has_app_context 彻底解决 Working outside of application context 报错
        """
        try:
            # 只有在 Flask 生命周期内才尝试访问 current_app
            if not has_app_context():
                return None
            
            redis_url = current_app.config.get('REDIS_URL')
            if not redis_url:
                return None
            return redis.from_url(redis_url, decode_responses=True)
        except Exception as e:
            # 打印到控制台但不抛出异常，确保业务不中断
            print(f"⚠️ Redis Context 保护触发: {e}")
            return None

    @classmethod
    def batch_get_valuation(cls, codes):
        """
        🚀 核心优化：使用天天基金专用批量实时估值接口
        接口地址格式: http://fundgz.1234567.com.cn/js/list/{codes}.js
        """
        if not codes:
            return {}

        results = {}
        r = cls.get_redis()
        
        # 1. 优先尝试从 Redis 批量读取缓存 (mget)
        remaining_codes = []
        if r:
            try:
                keys = [f"fund_nav:{c}" for c in codes]
                cached_values = r.mget(keys)
                for i, val in enumerate(cached_values):
                    if val:
                        data = json.loads(val)
                        results[codes[i]] = {
                            "code": codes[i],
                            "name": data.get('name'),
                            "nav": data.get('nav'),
                            "gszzl": data.get('daily_pct'),
                            "gztime": data.get('update_time')
                        }
                    else:
                        remaining_codes.append(codes[i])
            except:
                remaining_codes = codes
        else:
            remaining_codes = codes

        # 如果缓存全命中，直接返回
        if not remaining_codes:
            return results

        # 2. 调用天天基金批量极速接口
        try:
            # 将代码列表拼成 000001,000002 格式
            code_str = ",".join(clean_codes)
            timestamp = int(time.time() * 1000)
            # 天天基金批量接口地址
            url = f"http://fundgz.1234567.com.cn/js/list/{code_str}.js?rt={timestamp}"
            
            # 🟢 关键：必须伪装得像浏览器，否则会被返回空或 403
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": "http://fund.eastmoney.com/",
                "Accept": "*/*"
            }
            
            print(f"📡 正在爬取行情: {url}") # 调试用：去云托管日志看这个 URL 点开有没有数据
            
            # 使用 verify=False 绕过你之前遇到的 SSL 证书问题
            resp = requests.get(url, headers=headers, timeout=5, verify=False)
            
            # 接口返回格式示例: jsonpgz({"000001":{...},"000002":{...}});
            match = re.search(r'jsonpgz\((.*)\);', resp.text)
            if match:
                raw_json = json.loads(match.group(1))
                for code, item in raw_json.items():
                    val_data = {
                        "code": code,
                        "name": item.get('name'),
                        "nav": float(item.get('dwjz', 1.0)),
                        "gszzl": float(item.get('gszzl', 0.0)),
                        "gztime": item.get('gztime', '')
                    }
                    results[code] = val_data
                    
                    # 异步写入缓存（如果不报错的话）
                    if r:
                        try:
                            cache_item = {
                                "name": val_data['name'],
                                "nav": val_data['nav'],
                                "daily_pct": val_data['gszzl'],
                                "update_time": val_data['gztime']
                            }
                            r.setex(f"fund_nav:{code}", 600, json.dumps(cache_item))
                        except: pass
        except Exception as e:
            print(f"❌ 批量抓取行情异常: {e}")

        return results

    @classmethod
    def get_fund_data(cls, code):
        """单只查询时，也复用批量逻辑"""
        res = cls.batch_get_valuation([code])
        if code in res:
            data = res[code]
            return {
                "name": data['name'],
                "nav": data['nav'],
                "daily_pct": data['gszzl'],
                "update_time": data['gztime']
            }
        return cls._fallback_get_fund_data(code)

    @staticmethod
    def _fallback_get_fund_data(code):
        return {
            "name": f"未知基金{code}",
            "nav": 1.0,
            "daily_pct": 0.0,
            "update_time": "N/A"
        }