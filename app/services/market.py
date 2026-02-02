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

    @classmethod
    def get_fund_quote(cls, code):
        """
        🚀 核心：天天基金实时行情（无需 Token，全时段可用）
        """
        try:
            # 使用毫秒级时间戳防止缓存
            ts = int(time.time() * 1000)
            url = f"http://fundgz.1234567.com.cn/js/{code}.js?rt={ts}"
            
            resp = requests.get(url, headers=cls._HEADERS, timeout=5)
            # 解析 jsonpgz(...) 格式
            match = re.search(r'jsonpgz\((.*)\);', resp.text)
            
            if not match:
                logger.warning(f"无法解析基金代码或代码不存在: {code}")
                return code, None

            # 这里的 json.loads 必须配对正确
            data = json.loads(match.group(1))
            
            # 🚀 关键修复点：先提取原始值，再安全转换
            # dwjz: 昨日单位净值 | gsz: 当前估值净值 | gszzl: 估值涨幅
            raw_nav = data.get('dwjz')
            raw_gsz = data.get('gsz')
            raw_pct = data.get('gszzl')

            # 转换为 float，如果不存在则使用 1.0 或 0.0 保底
            nav = float(raw_nav) if raw_nav else 1.0
            gsz = float(raw_gsz) if raw_gsz else nav # 非交易时间估值通常等于净值
            pct = float(raw_pct) if raw_pct else 0.0

            return code, {
                "code": code,
                "name": data.get('name'),
                "nav": round(nav, 4),
                "gsz": round(gsz, 4),
                "gszzl": round(pct, 2),
                "gztime": data.get('gztime', '--:--'),
                "source": "tiantian"
            }
        except Exception as e:
            logger.error(f"⚠️ 天天基金接口异常 {code}: {str(e)}")
            return code, None

    @classmethod
    def batch_get_valuation(cls, fund_items):
        """
        🚀 批量获取入口：支持多线程并发
        """
        # 兼容处理：如果是代码字符串列表，转为字典格式
        if fund_items and isinstance(fund_items[0], str):
            fund_items = [{'code': c} for c in fund_items]
        
        if not fund_items:
            return {}

        results = {}

        def _worker(item):
            code = item.get('code')
            if not code: return None
            return cls.get_fund_quote(code)

        # 默认使用 5 个线程，避免频繁请求被封 IP
        with ThreadPoolExecutor(max_workers=5) as executor:
            responses = list(executor.map(_worker, fund_items))
            for res in responses:
                # 只有当抓取成功且数据体不为 None 时才存入
                if res and res[1]:
                    results[res[0]] = res[1]
                elif res:
                    # 彻底失败时，返回一个基础结构防止后端业务逻辑报错
                    results[res[0]] = {
                        "code": res[0], "nav": 0.0, "gsz": 0.0, "gszzl": 0.0,
                        "source": "error_fallback"
                    }

        return results

    @classmethod
    def get_single_quote(cls, code):
        """
        🚀 单只基金抓取入口
        """
        res = cls.get_fund_quote(code)
        return res[1] if res else None