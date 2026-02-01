# app/services/task_service.py
import akshare as ak
import json
import os
from flask import current_app

class TaskService:
    @staticmethod
    def update_fund_json():
        """
        定时任务：全量更新基金名称-代码映射文件
        """
        print("⏰ 开始执行定时任务：更新 funds.json ...")
        try:
            # 1. 拉取数据
            df = ak.fund_name_em()
            fund_map = dict(zip(df['基金简称'], df['基金代码']))
            
            # 2. 确定路径 (指向 app/data/funds.json)
            # 注意：在 Flask 应用上下文中，建议使用 absolute path
            base_dir = os.path.dirname(os.path.dirname(__file__)) # 定位到 app/
            save_path = os.path.join(base_dir, 'data', 'funds.json')
            
            # 确保目录存在
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            
            # 3. 写入文件
            with open(save_path, 'w', encoding='utf-8') as f:
                json.dump(fund_map, f, ensure_ascii=False)
                
            print(f"✅ 定时任务完成：已更新 {len(fund_map)} 条基金数据")
            
            # 4. 可选：更新完后，清除一下内存里的缓存 (如果有的话)
            from app.services.wechat_ocr import WeChatOCRService
            WeChatOCRService._fund_map = None 
            
        except Exception as e:
            print(f"❌ 定时任务失败: {str(e)}")