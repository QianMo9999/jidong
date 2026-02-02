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
        # 路由分发
        if cls.is_exchange_traded(code):
            return cls.get_etf_quote_sina(code) # 走新浪/腾讯
        return cls.get_otc_quote_tiantian(code) # 走天天基金
    
    @classmethod
    def get_etf_quote_sina(cls, code):
        """🛡️ 新浪财经接口：支持场内 ETF 基金"""
        try:
            # 新浪接口：sz+代码 或 sh+代码
            symbol = f"sz{code}" if code.startswith(('1', '15')) else f"sh{code}"
            url = f"http://hq.sinajs.cn/list={symbol}"
            
            # 注意：新浪接口可能需要特定的 Referer
            headers = {"Referer": "http://finance.sina.com.cn"}
            resp = requests.get(url, headers=headers, timeout=3)
            
            # 解析数据：var hq_str_sz159586="...,现价,昨日收盘,..."
            content = resp.text
            if len(content) < 50: return code, None
            
            data = content.split('=')[1].split(',')
            name = data[0].strip('"')
            curr = float(data[3]) # 当前价
            yest = float(data[2]) # 昨收
            
            return code, {
                "code": code,
                "name": name,
                "nav": yest,
                "gsz": curr,
                "gszzl": round((curr - yest) / yest * 100, 2) if yest > 0 else 0,
                "source": "sina_etf"
            }
        except:
            return code, None
        
    @classmethod
    def is_exchange_traded(cls, code):
        """
        🛡️ 精准判断是否为场内基金
        """
        if not code or len(code) != 6:
            return False
            
        # 定义场内基金特征号段
        # 50-52: 沪市 ETF/LOF | 56, 58: 沪市新号段
        # 15: 深市 ETF | 16: 深市 LOF | 18: 深市封闭式
        exchange_prefixes = ('50', '51', '52', '56', '58', '15', '16', '18')
        
        return code.startswith(exchange_prefixes)
    
    @classmethod
    def get_fund_quote(cls, code):
        # 1. 判断路由
        if cls.is_exchange_traded(code):
            # 场内基金：走新浪/腾讯接口，获取实时交易价格
            return cls.get_etf_quote_sina(code)
        else:
            # 场外基金：走天天基金接口，获取实时估值
            return cls.get_otc_quote_tiantian(code)

    @classmethod
    def get_otc_quote_tiantian(cls, code):
        """原有天天基金逻辑，增加内容校验防止解析 HTML 报错"""
        try:                      
            ts = int(time.time() * 1000)
            url = f"http://fundgz.1234567.com.cn/js/{code}.js?rt={ts}"
            
            resp = requests.get(url, headers=cls._HEADERS, timeout=5)
            # 🛡️ 关键：先检查是否为有效 JS 内容，防止被封 IP 返回 HTML 导致报错
            if not resp.text.startswith('jsonpgz'):
                logger.error(f"天天基金接口返回异常内容: {code}")
                return code, None
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