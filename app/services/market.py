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

    @classmethod
    def batch_get_valuation(cls, codes):
        """
        🚀 使用 AkShare 获取基金实时估算数据 (替代天天基金接口)
        说明: 此接口返回的是交易时间内的实时估算数据，非交易时间可能无数据。
        """
        if not codes:
            return {}

        results = {}
        
        # 1. 调用 AkShare 实时估值接口
        # 注意: 该接口可能返回大量数据，我们根据codes进行过滤
        try:
            # 获取所有有估值数据的基金列表
            estimation_df = ak.fund_em_value_estimation()
            
            # 将接口返回的DataFrame的索引（基金代码）转为字符串，便于匹配
            estimation_df.index = estimation_df.index.map(str)
            
            # 根据传入的codes列表进行筛选
            for code in codes:
                clean_code = str(code).strip()
                if clean_code in estimation_df.index:
                    fund_data = estimation_df.loc[clean_code]
                    
                    # 提取关键字段，注意字段名可能随AkShare版本变化，请根据实际情况调整
                    # ‘估算净值’， ‘估算涨跌幅’
                    results[clean_code] = {
                        "code": clean_code,
                        "name": fund_data.get('名称', 'N/A'),
                        "nav": fund_data.get('估算净值', 0.0),  # 当前估算净值
                        "gszzl": fund_data.get('估算涨跌幅', 0.0),  # 估算涨幅（百分比）
                        "gztime": fund_data.get('估值时间', ''),
                        # 以下为原接口可能没有的补充信息
                        "last_nav": fund_data.get('最新净值', 0.0),  # 前一交易日官方净值
                        "nav_date": fund_data.get('净值日期', ''),
                    }
                else:
                    # 如果code不在估值列表中，可以记录或尝试其他接口
                    results[clean_code] = {
                        "code": clean_code,
                        "error": "未找到该基金的实时估值数据"
                    }
                    
        except Exception as e:
            print(f"❌ 通过 AkShare 获取估值数据异常: {e}")
            # 可以选择在这里降级，尝试使用你的原接口或其他备用接口
            return {"error": f"数据获取失败: {str(e)}"}

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