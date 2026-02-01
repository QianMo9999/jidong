from datetime import datetime

def format_currency(value):
    """格式化货币显示"""
    try:
        return f"{float(value):,.2f}"
    except (ValueError, TypeError):
        return "0.00"

def get_now_str():
    """获取当前时间字符串"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def calculate_yield(current_val, cost_val):
    """计算简单收益率"""
    if cost_val == 0:
        return 0
    return round(((current_val - cost_val) / cost_val) * 100, 2)