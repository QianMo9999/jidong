import redis
import json
import requests
import re
import time
from flask import current_app
from concurrent.futures import ThreadPoolExecutor

class MarketService:
    @staticmethod
    def get_redis():
        return redis.from_url(current_app.config['REDIS_URL'], decode_responses=True)

    @classmethod
    def get_fund_data(cls, code):
        r = cls.get_redis()
        cache_key = f"fund_nav:{code}"
        
        # ============================================
        # 🟢 1. 读缓存 (带 0 值过滤)
        # ============================================
        try:
            cached = r.get(cache_key)
            if cached:
                data = json.loads(cached)
                # 检查缓存是否有效：净值必须 > 0，且名字不能包含"未知"
                nav = float(data.get('nav', 0))
                name = data.get('name', '')
                
                if nav > 0.0001 and "未知基金" not in name:
                    return data
                else:
                    # 如果缓存是坏的，删掉它，强制刷新
                    r.delete(cache_key)
        except:
            pass

        # ============================================
        # 🟢 2. 策略A：天天基金极速接口
        # ============================================
        try:
            timestamp = int(time.time() * 1000)
            url = f"http://fundgz.1234567.com.cn/js/{code}.js?rt={timestamp}"
            headers = {"User-Agent": "Mozilla/5.0", "Referer": "http://fund.eastmoney.com/"}
            resp = requests.get(url, headers=headers, timeout=2)
            
            match = re.search(r'jsonpgz\((.*)\);', resp.text)
            if match and match.group(1):
                raw_data = json.loads(match.group(1))
                
                nav = float(raw_data.get('dwjz', 0)) # 默认为 0
                
                # 🚨 核心拦截：如果接口通了，但净值是 0，说明这个接口对这只基金没用
                if nav <= 0.0001:
                    raise Exception(f"极速接口返回无效净值: {nav}")

                data = {
                    "name": raw_data.get('name', f"未知基金{code}"), 
                    "nav": nav,
                    "daily_pct": float(raw_data.get('gszzl', 0.0)),
                    "update_time": raw_data.get('gztime', '')
                }
                r.setex(cache_key, 600, json.dumps(data))
                return data
        except Exception as e:
            # 只有出错或净值为0时，才会走到这里
            pass 

        # ============================================
        # 🟢 3. 策略B：交易所场内行情 (解决 LOF/ETF 返回 0 的问题)
        # ============================================
        try:
            exchange_data = cls._fetch_exchange_quote(code)
            if exchange_data:
                # 再次检查交易所返回的净值
                if exchange_data['nav'] > 0.0001:
                    r.setex(cache_key, 600, json.dumps(exchange_data))
                    return exchange_data
        except:
            pass

        # ============================================
        # 🟢 4. 策略C：AkShare 兜底 (最后的防线)
        # ============================================
        return cls._fallback_get_fund_data(code)

    @classmethod
    def _fetch_exchange_quote(cls, code):
        try:
            market_id = "1" if code.startswith(('5', '6')) else "0"
            url = "https://push2.eastmoney.com/api/qt/stock/get"
            params = {"secid": f"{market_id}.{code}", "fields": "f58,f43,f170,f60"}
            
            resp = requests.get(url, params=params, timeout=3)
            data = resp.json()
            
            if data and data.get('data'):
                d = data['data']
                price = d.get('f43', 0)
                if price == '-' or str(price) == '0': price = d.get('f60', 0) # 昨收兜底
                
                try: price = float(price)
                except: price = 0.0
                
                # 如果价格还是 0，返回 None，交给 AkShare
                if price <= 0.0001: return None

                return {
                    "name": d.get('f58', f"未知{code}"),
                    "nav": price, 
                    "daily_pct": float(d.get('f170', 0)),
                    "update_time": time.strftime("%Y-%m-%d %H:%M")
                }
            return None
        except: return None

    @classmethod
    def _fallback_get_fund_data(cls, code):
        try:
            import akshare as ak
            # 这是一个历史数据接口，必定有值
            df = ak.fund_open_fund_info_em(symbol=code, indicator="单位净值走势")
            if df.empty: return None
            latest = df.iloc[-1]
            
            nav = float(latest['单位净值'])
            # 即使是兜底，也要检查
            if nav <= 0.0001: return None

            data = {
                "name": f"未知基金{code}",
                "nav": nav,
                "daily_pct": float(latest['日增长率']) if '日增长率' in latest else 0.0,
                "update_time": str(latest['净值日期'])
            }
            # 兜底数据存 5 分钟
            r = cls.get_redis()
            r.setex(f"fund_nav:{code}", 300, json.dumps(data))
            return data
        except:
            return None

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