# 鸿蒙应用更新监控与推送插件

一个用于监控华为鸿蒙应用市场（AppGallery）应用版本更新的AstrBot插件，自动检测应用更新并推送通知。

## 🎯 功能特性

- 🔍 **自动监控**：定时检查鸿蒙应用市场中的应用版本更新
- 📱 **多应用支持**：同时监控多个应用，支持自定义应用列表
- 🔔 **智能通知**：支持群组和用户通知，发现更新时自动推送
- ⚙️ **灵活配置**：通过Web界面轻松配置所有参数
- 🛠️ **便捷管理**：提供丰富的指令进行状态查看和管理
- 📊 **数据持久化**：记录版本信息，避免重复通知

## 📦 安装要求

### 环境要求
- Python 3.8+
- AstrBot 3.5.10+
- Playwright（自动安装）

### 安装步骤

1. **安装插件**
   ```bash
   # 将插件目录放入AstrBot的plugins目录
   cp -r harmony_app_monitor /path/to/astrbot/plugins/
   ```

2. **安装依赖**
   ```bash
   # 进入插件目录
   cd /path/to/astrbot/plugins/harmony_app_monitor
   
   # 安装Python依赖
   pip install playwright
   
   # 安装浏览器
   playwright install chromium
   ```

3. **重启AstrBot**
   ```bash
   systemctl restart astrbot  # 或使用您的启动方式
   ```

## ⚙️ 配置说明

### Web界面配置
在AstrBot管理面板中配置以下参数：

| 配置项 | 类型 | 说明 | 默认值 |
|--------|------|------|--------|
| 应用名称列表 | text | 每行一个应用名称 | 一日记账 |
| 应用详情页链接列表 | text | 每行一个应用详情页链接 | 示例链接 |
| 版本选择器列表 | text | 每行一个CSS选择器 | span.content-value |
| 检查间隔（分钟） | int | 自动检查的时间间隔 | 30 |
| 指令前缀 | string | 插件指令的前缀字符 | / |
| 推送通知的群组 | text | 每行一个群组ID | 空 |
| 推送通知的用户 | text | 每行一个用户ID | 空 |
| 启用调试日志 | bool | 是否启用详细调试日志 | false |

### 配置示例
```
应用名称列表：
一日记账
华为视频

应用详情页链接列表：
https://appgallery.huawei.com/app/detail?id=com.ericple.onebill
https://appgallery.huawei.com/app/detail?id=com.huawei.himovie

版本选择器列表：
span.content-value
span.version-info

推送通知的群组：
123456789
987654321
```

## 📖 使用方法

### 基础指令

| 指令 | 功能 | 示例 |
|------|------|------|
| `/status` | 查看插件状态 | `/status` |
| `/check` | 立即检查更新 | `/check` |
| `/list` | 列出监控应用 | `/list` |
| `/notify` | 查看通知配置 | `/notify` |
| `/refresh` | 刷新配置 | `/refresh` |
| `/help` | 显示帮助 | `/help` |

### 通知管理指令

| 指令 | 功能 | 示例 |
|------|------|------|
| `/add_notify <类型> <ID>` | 添加通知目标 | `/add_notify group 123456789` |
| `/del_notify <类型> <ID>` | 删除通知目标 | `/del_notify user 987654321` |

### 使用示例

1. **查看状态**
   ```
   /status
   
   输出：
   📊 鸿蒙监控状态
   • 监控应用: 3个
   • 检查间隔: 30分钟
   • 运行状态: ✅ 运行中
   • Playwright: ✅ 可用
   • 通知群组: 2个
   • 通知用户: 1个
   • 版本记录: 3个
   • 调试模式: ❌ 关闭
   ```

2. **立即检查更新**
   ```
   /check
   
   输出：
   🔍 正在检查所有应用更新，请稍候...
   ✅ 检查完成！耗时: 12.5秒
   
   📋 当前版本信息:
     • 一日记账: v2.3.1
     • 华为视频: v11.0.5
     • 华为音乐: v9.1.2
   ```

3. **添加通知群组**
   ```
   /add_notify group 123456789
   
   输出：
   ✅ 已添加通知群组: 123456789
   ```

## 🔧 故障排除

### 常见问题

1. **插件无法启动**
   - 检查Playwright是否安装正确：`playwright --version`
   - 查看AstrBot日志，确认错误信息
   - 检查配置格式是否正确

2. **无法获取版本信息**
   - 检查网络连接是否正常
   - 确认应用链接是否有效
   - 检查CSS选择器是否正确
   - 查看调试日志：启用`enable_debug_log`配置项

3. **通知发送失败**
   - 检查群组/用户ID是否正确
   - 确认机器人有发送消息的权限
   - 查看AstrBot的消息发送日志

### 日志查看

```bash
# 查看AstrBot日志
journalctl -u astrbot -f

# 或查看日志文件
tail -f /var/log/astrbot/astrbot.log
```

### 调试模式
在Web界面中启用`启用调试日志`配置项，插件将输出详细的调试信息。

## 🚀 高级功能

### 自定义CSS选择器
不同的应用页面可能使用不同的CSS选择器来显示版本号。您可以通过以下方式获取正确的选择器：

1. 打开浏览器开发者工具（F12）
2. 使用元素选择器定位版本号
3. 复制版本号元素的CSS选择器

常见的选择器：
- `span.content-value`
- `div.version-text`
- `span.version-info`
- `p.version-number`

### 添加新应用
1. 在Web界面配置中添加应用名称、链接和选择器
2. 确保三者的行数对应
3. 保存配置后使用`/refresh`指令刷新
4. 使用`/check`指令测试获取版本

### 批量导入配置
您可以将配置导出为JSON格式，便于批量管理：

1. 在配置文件中直接编辑
2. 或通过`/export`指令导出配置模板
3. 修改后重新导入

## 📁 文件结构

```
harmony_app_monitor/
├── main.py              # 插件主程序
├── _conf_schema.json    # 配置定义文件
├── README.md           # 本说明文件
├── harmony_versions.json # 版本记录（自动生成）
└── user_config.json    # 用户配置（自动生成）
```

## 🔄 更新日志

### v1.0.0 (2024-01-01)
- ✅ 首次发布
- ✅ 基础监控功能
- ✅ 多应用支持
- ✅ Web界面配置
- ✅ 通知系统
- ✅ 指令管理

## 📄 许可证

本项目采用 MIT 许可证。详见 [LICENSE](LICENSE) 文件。

## 🤝 贡献指南

欢迎提交Issue和Pull Request！

1. Fork 本仓库
2. 创建功能分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

## 💬 支持与反馈

如果您遇到问题或有建议：

1. 查看 [GitHub Issues](https://github.com/your-repo/issues)
2. 提交新的Issue
3. 或通过邮件联系我们

## 🙏 致谢

感谢以下项目：
- [AstrBot](https://github.com/Soulter/AstrBot) - 优秀的机器人框架
- [Playwright](https://playwright.dev/) - 强大的浏览器自动化工具
- 所有贡献者和用户

---

**Happy Monitoring!** 🎉