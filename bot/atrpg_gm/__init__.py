"""atrpg_gm 插件包。

NoneBot 加载本包时只执行 __init__.py，不会自动导入子模块。
必须显式 import .gm，gm.py 顶层的 on_message(...) 才会执行并注册 matcher。
"""

try:
    from . import gm  # noqa: F401 — 副作用导入：注册主持人 matcher
except ImportError:
    pass  # web_api 模式下不依赖 NoneBot，跳过 gm 注册
