import requests
import re
import time
import json
import logging
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

# 配置日志
logger = logging.getLogger(__name__)

class MarketService:
    # 模拟浏览器指纹
    _HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.fund123.cn/fund",
        "X-API-Key": "foobar",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    # 内存缓存存根
    _CONTEXT = {
        "session": requests.Session(),
        "csrf": None,
        "last_init": 0,
        "key_cache": {} 
    }

    @classmethod
    def _refresh_context(cls):
        """🛡️ 自动维护 CSRF 令牌（每 20 分钟刷新）"""
        now = time.time()
        if cls._CONTEXT["csrf"] and (now - cls._CONTEXT["last_init"] < 1200):
            return

        try:
            logger.info("🔄 正在刷新蚂蚁基金 API 上下文...")
            res = cls._CONTEXT["session"].get(
                "https://www.fund123.cn/fund", 
                headers=cls._HEADERS, 
                timeout=10, 
                verify=False
            )
            csrf_match = re.findall(r'\"csrf\":\"(.*?)\"', res.text)
            if csrf_match:
                cls._CONTEXT["csrf"] = csrf_match[0]
                cls._CONTEXT["last_init"] = now
                cls._CONTEXT["session"].headers.update({"_csrf": cls._CONTEXT["csrf"]})
                logger.info(f"✅ 上下文初始化成功, CSRF: {cls._CONTEXT['csrf'][:8]}...")
            else:
                logger.error("❌ 无法解析 CSRF 令牌")
        except Exception as e:
            logger.error(f"⚠️ 初始化蚂蚁接口失败: {str(e)}")

    @classmethod
    def fetch_fund_key_from_api(cls, code):
        """🚀 供 Route 调用：添加基金时同步获取 key"""
        cls._refresh_context()
        if code in cls._CONTEXT["key_cache"]:
            return cls._CONTEXT["key_cache"][code]
        return cls._fetch_fund_key(code)

    @classmethod
    def _fetch_fund_key(cls, code):
        """🛡️ 内部方法：从搜索接口换取 fund_key"""
        try:
            search_url = f"https://www.fund123.cn/api/fund/searchFund"
            data = {"fundCode": code}
            resp = cls._CONTEXT["session"].post(
                search_url, 
                params={"_csrf": cls._CONTEXT["csrf"]}, 
                json=data, 
                headers=cls._HEADERS, 
                timeout=5
            )
            res = resp.json()
            if res.get("success") and res.get("fundInfo"):
                f_key = res["fundInfo"]["key"]
                cls._CONTEXT["key_cache"][code] = f_key
                return f_key
        except Exception as e:
            logger.warning(f"无法获取代码 {code} 的 FundKey: {e}")
        return None

    @classmethod
    def get_quote_by_key(cls, code, f_key):
        """🚀 核心：尝试蚂蚁接口行情，失败则兜底"""
        try:
            url = "https://www.fund123.cn/api/fund/queryFundEstimateIntraday"
            today = datetime.now().strftime("%Y-%m-%d")
            tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
            
            payload = {
                "startTime": today, "endTime": tomorrow,
                "limit": 1, "productId": f_key,
                "format": True, "source": "WEALTHBFFWEB"
            }
            
            resp = cls._CONTEXT["session"].post(
                url, 
                params={"_csrf": cls._CONTEXT["csrf"]}, 
                json=payload, 
                timeout=3
            )
            res_json = resp.json()

            if res_json.get("success") and res_json.get("list"):
                latest = res_json["list"][-1]
                return code, {
                    "code": code,
                    "name": latest.get('fundName'),
                    "nav": float(latest.get('lastNetValue', 0.0)),
                    "gsz": float(latest.get('forecastNetValue', 0.0)),
                    "gszzl": float(latest.get('forecastGrowth', 0.0)) * 100,
                    "gztime": datetime.fromtimestamp(latest['time'] / 1000).strftime("%H:%M:%S"),
                    "fund_key": f_key, # 传回 key，方便数据库补录
                    "source": "ant"
                }
        except Exception as e:
            logger.warning(f"⚠️ 蚂蚁接口对 {code} 失效，切换兜底: {e}")

        return cls.fallback_to_tiantian(code)

    @classmethod
    def fallback_to_tiantian(cls, code):
        """🛡️ 天天基金兜底（无需 Token，万能备胎）"""
        try:
            url = f"http://fundgz.1234567.com.cn/js/{code}.js?rt={int(time.time())}"
            resp = requests.get(url, timeout=3)
            match = re.search(r'jsonpgz\((.*)\);', resp.text)
            if match:
                data = json.loads(match.group(1))
                return code, {
                    "code": code,
                    "name": data.get('name'),
                    "nav": float(data.get('dwjz', 1.0)),
                    "gsz": float(data.get('gsz', 1.0)),
                    "gszzl": float(data.get('gszzl', 0.0)),
                    "gztime": data.get('gztime'),
                    "source": "tiantian_fallback"
                }
        except: pass
        return code, None

    @classmethod
    def batch_get_valuation(cls, fund_items):
        """🚀 生产级入口"""
        if not fund_items: return {}
        cls._refresh_context()
        results = {}

        def _worker(item):
            code = item['code']
            f_key = item.get('key')
            if not f_key:
                f_key = cls._fetch_fund_key(code)
            if not f_key:
                return cls.fallback_to_tiantian(code)
            return cls.get_quote_by_key(code, f_key)

        with ThreadPoolExecutor(max_workers=5) as executor:
            responses = list(executor.map(_worker, fund_items))
            for res in responses:
                if res: results[res[0]] = res[1]

        return results