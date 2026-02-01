# scripts/init_fund_data.py
import akshare as ak
import json
import os

def generate_fund_map():
    print("正在拉取全量基金数据 (可能需要几十秒)...")
    try:
        # 获取天天基金的所有基金代码和名称
        df = ak.fund_name_em()
        # df 结构: [基金代码, 拼音缩写, 基金简称, 基金类型, 拼音全称]
        
        # 转换为字典 { "基金简称": "基金代码" }
        # 注意：这里我们做一个反向映射，方便用名字查代码
        fund_map = dict(zip(df['基金简称'], df['基金代码']))
        
        # 保存为 JSON 文件到 app/data 目录
        save_path = os.path.join(os.path.dirname(__file__), '../app/data/funds.json')
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        
        with open(save_path, 'w', encoding='utf-8') as f:
            json.dump(fund_map, f, ensure_ascii=False)
            
        print(f"成功保存 {len(fund_map)} 条基金数据到 {save_path}")
        
    except Exception as e:
        print(f"获取失败: {e}")

if __name__ == '__main__':
    generate_fund_map()