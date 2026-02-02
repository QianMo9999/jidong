import requests
import time
import json
from concurrent.futures import ThreadPoolExecutor

class MarketService:
    @staticmethod
    def get_headers():
        return {
            "Content-Type": "application/json",
            "Referer": "https://www.fund123.cn/fund",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "X-API-Key": "foobar"  # MaYiFund 验证过的有效 Key
        }

    @classmethod
    def get_single_quote(cls, code):
        """
        🚀 接口 A：蚂蚁基金实时估值 (主要来源)
        特点：数据包小，包含昨日净值和今日实时估算
        """
        code = str(code).strip()
        try:
            url = "https://www.fund123.cn/api/fund/queryFundEstimateIntraday"
            today = time.strftime("%Y-%m-%d")
            tomorrow = (time.strftime("%Y-%m-%d", time.localtime(time.time() + 86400)))
            
            payload = {
                "productId": code,
                "startTime": today,
                "endTime": tomorrow,
                "limit": 1,
                "format": True,
                "source": "WEALTHBFFWEB"
            }
            
            resp = requests.post(url, json=payload, headers=cls.get_headers(), timeout=5, verify=False)
            res = resp.json()

            if res.get("success") and res.get("list"):
                data = res["list"][-1]
                # 统一字段名映射
                return code, {
                    "code": code,
                    "name": data.get('fundName', f"基金{code}"),
                    "nav": float(data.get('lastNetValue', 1.0)),     # 昨日净值
                    "gsz": float(data.get('forecastNetValue', 1.0)), # 今日估算
                    "gszzl": float(data.get('forecastGrowth', 0.0)) * 100, # 涨幅(%)
                    "gztime": time.strftime("%H:%M:%S", time.localtime(data['time'] / 1000)),
                    "source": "mayi"
                }
        except Exception:
            pass
        
        # 🟢 接口 B：如果蚂蚁失败，自动回退到天天基金 (BackUp)
        return cls._fallback_tiantian_quote(code)

    @classmethod
    def _fallback_tiantian_quote(cls, code):
        """天天基金备份抓取逻辑"""
        try:
            url = f"http://fundgz.1234567.com.cn/js/{code}.js?rt={int(time.time()*1000)}"
            resp = requests.get(url, timeout=3, verify=False)
            import re
            match = re.search(r'jsonpgz\((.*)\);', resp.text)
            if match:
                item = json.loads(match.group(1))
                return code, {
                    "code": code,
                    "name": item.get('name'),
                    "nav": float(item.get('dwjz', 1.0)),
                    "gsz": float(item.get('gsz', 1.0)),
                    "gszzl": float(item.get('gszzl', 0.0)),
                    "gztime": item.get('gztime', ''),
                    "source": "tiantian"
                }
        except: pass
        return code, None

    @classmethod
    def batch_get_valuation(cls, codes):
        """
        🚀 模仿 MaYiFund 的并发机制
        使用 ThreadPoolExecutor 模拟信号量限制，确保请求不被封禁
        """
        if not codes: return {}
        clean_codes = list(set([str(c).strip() for c in codes if c]))
        results = {}

        # 蚂蚁服务器对高频请求敏感，建议 max_workers 设为 5
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(cls.get_single_quote, c) for c in clean_codes]
            for future in futures:
                code, data = future.result()
                if data:
                    results[code] = data
        
        print(f"✅ 多源行情抓取完成: 成功 {len(results)}/{len(clean_codes)}")
        return results