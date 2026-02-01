import redis
import json
import requests
import re
import time
from flask import current_app
from concurrent.futures import ThreadPoolExecutor

class MarketService:
    import re
import time
import json
import requests
import redis
from flask import current_app

class MarketService:
    @staticmethod
    def get_redis():
        """
        🟢 防御性获取 Redis 实例
        如果 config 中没有 REDIS_URL，或者连接失败，返回 None
        """
        try:
            redis_url = current_app.config.get('REDIS_URL')
            if not redis_url:
                # 提示：可以在云托管控制台环境变量中添加 REDIS_URL
                return None
            return redis.from_url(redis_url, decode_responses=True)
        except Exception as e:
            print(f"⚠️ Redis 连接异常: {e}")
            return None

    @classmethod
    def get_fund_data(cls, code):
        r = cls.get_redis()
        cache_key = f"fund_nav:{code}"
        
        # ============================================
        # 🟢 1. 读缓存 (带 Redis 存在性检查)
        # ============================================
        if r:
            try:
                cached = r.get(cache_key)
                if cached:
                    data = json.loads(cached)
                    nav = float(data.get('nav', 0))
                    name = data.get('name', '')
                    
                    if nav > 0.0001 and "未知基金" not in name:
                        return data
                    else:
                        r.delete(cache_key)
            except Exception as e:
                print(f"Redis 读取失败: {e}")

        # ============================================
        # 🟢 2. 策略A：天天基金极速接口
        # ============================================
        try:
            timestamp = int(time.time() * 1000)
            url = f"http://fundgz.1234567.com.cn/js/{code}.js?rt={timestamp}"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "http://fund.eastmoney.com/"
            }
            resp = requests.get(url, headers=headers, timeout=3)
            
            # 使用正则提取 JSON 内容
            match = re.search(r'jsonpgz\((.*)\);', resp.text)
            if match and match.group(1):
                raw_data = json.loads(match.group(1))
                nav = float(raw_data.get('dwjz', 0))
                
                if nav > 0.0001:
                    data = {
                        "name": raw_data.get('name', f"未知基金{code}"), 
                        "nav": nav,
                        "daily_pct": float(raw_data.get('gszzl', 0.0)),
                        "update_time": raw_data.get('gztime', '')
                    }
                    # 只有 Redis 可用时才写缓存
                    if r:
                        try:
                            r.setex(cache_key, 600, json.dumps(data))
                        except:
                            pass
                    return data
        except Exception as e:
            print(f"天天基金接口异常 ({code}): {e}")

        # ============================================
        # 🟢 3. 策略B：交易所场内行情 (LOF/ETF)
        # ============================================
        try:
            exchange_data = cls._fetch_exchange_quote(code)
            if exchange_data and exchange_data.get('nav', 0) > 0.0001:
                if r:
                    try:
                        r.setex(cache_key, 600, json.dumps(exchange_data))
                    except:
                        pass
                return exchange_data
        except Exception as e:
            print(f"交易所接口异常 ({code}): {e}")

        # ============================================
        # 🟢 4. 策略C：AkShare 兜底 (最后的防线)
        # ============================================
        return cls._fallback_get_fund_data(code)

    @staticmethod
    def _fetch_exchange_quote(code):
        """模拟交易所行情获取逻辑"""
        # 实际代码中应包含对应的爬虫逻辑
        return None

    @staticmethod
    def _fallback_get_fund_data(code):
        """模拟最后的兜底逻辑"""
        return {
            "name": f"未知基金{code}",
            "nav": 1.0,
            "daily_pct": 0.0,
            "update_time": "N/A"
        }

    
    @classmethod
    def batch_get_valuation(cls, codes):
        results = {}
        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_code = {executor.submit(cls.get_fund_data, code): code for code in codes}
            for future in future_to_code:
                code = future_to_code[future]
                try:
                    res = future.result()
                    if res:
                        results[code] = {
                            "code": code,
                            "name": res.get('name'),
                            "nav": res.get('nav'),
                            "gszzl": res.get('daily_pct'),
                            "gztime": res.get('update_time')
                        }
                except: pass
        return results