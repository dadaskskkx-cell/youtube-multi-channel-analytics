# YouTube Multi-Channel Analytics Tool

YouTube多频道收益数据采集工具，支持批量管理和采集多个YouTube频道的Analytics数据。

## 功能特性

- 多频道OAuth授权管理
- 批量采集频道收益数据
- 自动生成中文报表
- 图形化界面操作
- 支持自定义OAuth凭证

## 使用说明

详见 `YouTube工具使用说明.md`

## 文件说明

- `youtube_multi_token_manager.py` - 核心后端逻辑
- `youtube_multi_token_gui.py` - GUI界面
- `youtube_multi_token_gui.spec` - PyInstaller打包配置

## 依赖

- Python 3.8+
- google-auth
- google-auth-oauthlib
- google-api-python-client
- pandas
- openpyxl
