# 鸿蒙应用更新监控（AstralBot插件）

一款适配AstralBot的插件，用于实时监控鸿蒙应用商城指定应用的版本更新，并自动推送更新通知至机器人（支持企业微信/QQ/钉钉/飞书）。

## 特性
- ✅ 遵循AstralBot官方插件开发规范
- ✅ 定时检查应用版本，支持自定义检查间隔
- ✅ 自动对比历史版本，避免重复推送
- ✅ 内置反爬机制（请求重试、真实UA、连接池）
- ✅ 面板可视化配置，无需修改代码
- ✅ 整合到AstralBot统一日志系统

## 环境要求
- AstralBot ≥ v0.9.0
- Python ≥ 3.8
- 服务器可访问鸿蒙应用商城（https://appgallery.huawei.com）

## 安装方式
### 方式1：手动安装（推荐）
1. 将插件目录放入AstralBot插件根目录：
   ```bash
   # 官方默认插件目录
   cp -r harmony_app_monitor /usr/local/astrbot/plugins/
