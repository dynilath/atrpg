"""ATRPG Bot 启动入口。

启动流程：
1. 检查 .env 配置完整性（缺失则走交互式向导 config_setup.py）
2. nonebot.init() + 注册 QQ 官方适配器
3. 加载 atrpg_gm 插件
4. run

用法：
    python run.py            # 启动（首次缺失配置自动走向导）
    python run.py --setup    # 强制重跑配置向导
"""

from __future__ import annotations

import sys

# 注意：配置向导模块必须独立于 atrpg_gm 插件包导入。
# 若在 nonebot.load_from_toml() 之前 import atrpg_gm 的任何子模块，
# 会触发 "Module atrpg_gm is not loaded as a plugin" 错误。
import config_setup


def main() -> None:
    force_setup = "--setup" in sys.argv or "--reconfig" in sys.argv
    config_setup.ensure_config(force=force_setup)

    # 延迟到此处再 import nonebot，确保 .env 已就绪
    import nonebot
    from nonebot.adapters.qq import Adapter as QQAdapter

    nonebot.init()
    driver = nonebot.get_driver()
    driver.register_adapter(QQAdapter)
    nonebot.load_from_toml("pyproject.toml")
    nonebot.run()


if __name__ == "__main__":
    main()
