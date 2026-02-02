import re
import time
import json
import requests
import redis
import urllib3
from flask import current_app, has_app_context
import akshare as ak
import pandas as pd
import time

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

    import akshare as ak
import pandas as pd

class MarketService:
    @classmethod
    def batch_get_valuation(cls, codes):
        """
        🚀 核心优化：自动识别场内/场外基金并调用对应 AkShare 接口
        """
        if not codes:
            return {}

        results = {}
        etf_codes = []      # 场内基金 (ETF/LOF)
        regular_codes = []  # 场外基金 (普通开放式)

        # ==========================================
        # 🛡️ 1. 自动判断逻辑 (加固版)
        # ==========================================
        for code in codes:
            c = str(code).strip()
            # 沪市场内：50, 51, 52, 56, 58 开头
            # 深市场内：15, 16, 18 开头
            if c.startswith(('50', '51', '52', '56', '58', '15', '16', '18')):
                etf_codes.append(c)
            else:
                regular_codes.append(c)

        # ==========================================
        # 🟢 2. 获取场外基金实时估值 (fund_value_estimation_em)
        # ==========================================
        if regular_codes:
            try:
                # 注意：此接口返回的是全量数据，建议不要太频繁调用
                est_df = ak.fund_value_estimation_em()
                est_df['基金代码'] = est_df['基金代码'].astype(str)
                est_df.set_index('基金代码', inplace=True)

                for code in regular_codes:
                    if code in est_df.index:
                        row = est_df.loc[code]
                        results[code] = {
                            "code": code,
                            "name": row.get('基金简称', 'N/A'),
                            "nav": float(row.get('估算净值', 0.0)),
                            "gszzl": float(row.get('估算涨跌幅', 0.0)),
                            "gztime": row.get('估值时间', ''),
                            "type": "场外"
                        }
                    else:
                        results[code] = {"code": code, "error": "未找到估值", "type": "场外"}
            except Exception as e:
                print(f"❌ 场外获取失败: {e}")

        # ==========================================
        # 🔵 3. 获取场内基金实时行情 (fund_etf_spot_em)
        # ==========================================
        if etf_codes:
            try:
                # 获取场内 ETF/LOF 实时快照
                spot_df = ak.fund_etf_spot_em()
                spot_df['代码'] = spot_df['代码'].astype(str)
                spot_df.set_index('代码', inplace=True)

                for code in etf_codes:
                    if code in spot_df.index:
                        row = spot_df.loc[code]
                        results[code] = {
                            "code": code,
                            "name": row.get('名称', 'N/A'),
                            "nav": float(row.get('最新价', 0.0)),  # 场内交易看最新成交价
                            "gszzl": float(row.get('涨跌幅', 0.0)), # 场内实时涨跌
                            "gztime": row.get('数据复核时间', ''), # 对应交易时间
                            "type": "场内"
                        }
                    else:
                        results[code] = {"code": code, "error": "未找到行情", "type": "场内"}
            except Exception as e:
                print(f"❌ 场内获取失败: {e}")

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