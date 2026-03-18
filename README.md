# YouTube Multi-Channel Analytics Tool

YouTube多频道收益数据采集工具，支持批量管理和采集多个YouTube频道的Analytics数据。

## 功能特性

- 多频道OAuth授权管理
- 批量采集频道收益数据
- 自动生成中文报表
- 图形化界面操作
- 支持自定义OAuth凭证

## 快速开始

### 1. 安装依赖

```bash
pip install google-auth google-auth-oauthlib google-api-python-client pandas openpyxl
```

### 2. 配置OAuth凭证

1. 访问 [Google Cloud Console](https://console.cloud.google.com/)
2. 创建项目并启用 YouTube Data API v3 和 YouTube Analytics API
3. 创建 OAuth 2.0 客户端（Web应用类型）
4. 下载 `client_secrets.json` 放在程序目录

详细配置步骤见 [使用说明.md](./使用说明.md)

### 3. 运行程序

```bash
python youtube_multi_token_gui.py
```

## 文件说明

- `youtube_multi_token_manager.py` - 核心后端逻辑
- `youtube_multi_token_gui.py` - GUI界面
- `youtube_multi_token_gui.spec` - PyInstaller打包配置
- `使用说明.md` - 详细使用文档

## 注意事项

⚠️ **不要提交敏感文件到Git仓库：**
- `client_secrets.json` - OAuth凭证
- `tokens/` - 授权token目录
- `authorized_channels.xlsx` - 频道注册表
- `*.xlsx` - 采集数据文件
