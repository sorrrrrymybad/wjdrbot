# 无尽冬日国服挂机脚本

一个由于晨曦岛模式上线后挂机砍树收益大于离线收益为由开发的挂机脚本，不涉及到程序破解，目前仅适用于我自己的 `Redmi Note 10 Pro` （有相同手机的可以尝试直接使用），未来是否开发模拟器通用版本待定。

可以在电脑安装 ``ADB(Android Debug Bridge)`` 后连接自己的手机，打开手机的开发者模式并启用指针位置，修改 ``config.yaml`` 中对应的XY轴坐标，从而适配自己的手机。

## 📌 目前实现

✅ 自动仓库领取（体力需手动领取）  
✅ 自动联盟捐赠  
✅ 自动领取邮件  
✅ 自动刷新联盟总动员（目前仅支持860和520的练兵拳头）  
✅ 开启自动狩猎（需配合月卡）  
✅ 自动返回晨曦岛  

更多功能根据自用需求不断增加中...

## 🍢 API服务

程序会同时启动一个API服务用于远程管理，端口默认为 ``1234``，接口都需要配置请求头 `X-API-Key`

↔️ 结束进程

```sh
POST http://localhost:1234/process/stop
```

↔️ 获取任务列表

```sh
GET http://localhost:1234/tasks
```

↔️ 获取日志

```sh
# 获取最后100行日志（默认）
GET http://localhost:1234/logs

# 获取最后N行日志
GET http://localhost:1234/logs?lines=50
```

↔️ 修改任务开启状态

```sh
PUT http://localhost:1234/tasks
Content-Type: application/json

[
  {
    "name": "任务名称",
    "enabled": true/false
  }
]
```

↔️ 强制关闭App（用于重置坐标）

```sh
# 理论上知道包名可以关闭任何App
POST http://localhost:1234/apps/com.gof.china/close
```

## 🛠️ 如何配置并启动

### 🔧 安装依赖:

```sh
pip install -r requirements.txt
```

### 🔑 配置参数:

在根目录下新建一个 ``.env`` 文件，并配置

```sh
API_KEY=你的API请求密钥（需要配置请求头X-API-Key）

TELEGRAM_BOT_TOKEN=用于通知图片匹配结果的电报机器人Token
TELEGRAM_CHAT_ID=用于通知图片匹配结果的电报机器人Chat ID
```

### ▶️ 启动:

```sh
nohup python main.py > /dev/null 2>&1 &
```

日志会输出在 ``logs`` 文件夹
