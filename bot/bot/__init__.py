"""ATRPG QQ 群 AI 主持人 — bot 启动入口。

运行：
    cd bot
    ../../.workbuddy/.../python -m nonebot
或（已装 nbcli）：
    nb run
"""

import nonebot
from nonebot.adapters.qq import Adapter as QQAdapter

# 加载 .env
nonebot.init()

# 注册 QQ 官方 Bot 适配器
driver = nonebot.get_driver()
driver.register_adapter(QQAdapter)

# 加载插件
nonebot.load_from_toml("pyproject.toml")

if __name__ == "__main__":
    nonebot.run()
