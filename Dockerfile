# 使用 Python 3.9 官方精简镜像
FROM python:3.9-slim

# 设置工作目录
WORKDIR /app

# 设置时区为上海 (非常重要！否则你的基金更新时间会差8小时)
RUN ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime
RUN echo 'Asia/Shanghai' >/etc/timezone

# 复制依赖文件并安装
COPY requirements.txt .
# 使用阿里源加速安装，避免云端构建超时
RUN pip install --no-cache-dir -r requirements.txt -i http://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com
# 复制项目所有代码到容器
COPY . .

# 暴露 80 端口
EXPOSE 80

# 启动命令：使用 gunicorn 启动
# 假设你的入口文件是 run.py，里面初始化的变量叫 app
# 如果你的入口是 app.py，就把 run:app 改成 app:app
CMD ["gunicorn", "-w", "2", "--threads", "4", "-b", "0.0.0.0:80", "run:app"]