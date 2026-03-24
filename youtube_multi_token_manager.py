#!/usr/bin/env python
# -*- coding: utf-8 -*-

import argparse
import os
import pickle
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient import _auth
from requests.exceptions import RequestException

# 设置代理
def setup_proxy():
    """从环境变量读取代理设置"""
    http_proxy = os.environ.get('HTTP_PROXY') or os.environ.get('http_proxy')
    https_proxy = os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy')

    if http_proxy or https_proxy:
        proxy_dict = {}
        if https_proxy:
            proxy_dict['https'] = https_proxy
        if http_proxy:
            proxy_dict['http'] = http_proxy

        # 为googleapiclient设置代理
        _auth.httplib22.Http._auth_dynamic_proxy = proxy_dict.get('https') or proxy_dict.get('http')

# 初始化时设置代理
setup_proxy()

SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/yt-analytics-monetary.readonly",
]
ANALYTICS_LAG_DAYS = 3


import sys

def get_default_paths() -> Dict[str, Path]:
    home = Path(os.path.expanduser("~"))
    root = home / "youtube-analytics"

    # 如果是打包后的exe，数据保存到用户目录
    if getattr(sys, 'frozen', False):
        bundle_dir = Path(sys._MEIPASS)

        # 确保用户目录存在
        root.mkdir(parents=True, exist_ok=True)
        (root / "tokens").mkdir(exist_ok=True)

        # 首次运行时，复制client_secrets
        client_secrets = root / "client_secrets.json"
        if not client_secrets.exists():
            import shutil
            shutil.copy2(bundle_dir / "client_secrets.json", client_secrets)

        # 检查注册表文件
        registry = root / "authorized_channels.xlsx"

        # 如果注册表不存在，或者token目录为空，创建新的空注册表
        token_dir = root / "tokens"
        has_tokens = any(token_dir.glob("*.pickle")) if token_dir.exists() else False

        if not registry.exists() or not has_tokens:
            import pandas as pd
            empty_df = pd.DataFrame(columns=['updated_at', 'alias', 'channel_title', 'channel_id', 'custom_url', 'token_file', 'status'])
            empty_df.to_excel(registry, index=False)
    else:
        client_secrets = root / "client_secrets.json"
        registry = root / "authorized_channels.xlsx"
        token_dir = root / "tokens"

    return {
        "home": home,
        "root": root,
        "client_secrets": client_secrets,
        "token_dir": token_dir,
        "inactive_dir": root / "tokens_inactive",
        "registry": registry,
        "output": home / "Downloads" / "youtube_multi_channel_income.xlsx",
        "desktop_output": home / "Desktop" / "youtube_multi_channel_income.xlsx",
        "desktop_output_cn": home / "Desktop" / "youtube_multi_channel_income_cn_fixed.xlsx",
    }


def setup_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def sanitize_name(value: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]+', "_", value.strip())
    cleaned = re.sub(r"\s+", "_", cleaned)
    return cleaned[:80] or "channel"


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def load_credentials(client_secrets: Path, token_file: Path, force_reauth: bool, port: int) -> Credentials:
    creds: Optional[Credentials] = None

    if force_reauth and token_file.exists():
        token_file.unlink()

    if token_file.exists():
        with token_file.open("rb") as file_obj:
            creds = pickle.load(file_obj)

    if creds and creds.expired and creds.refresh_token:
        # 设置代理
        proxies = {}
        for key in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY']:
            if key in os.environ:
                proxies['https'] = os.environ.get('https_proxy') or os.environ.get('HTTPS_PROXY')
                proxies['http'] = os.environ.get('http_proxy') or os.environ.get('HTTP_PROXY')
                break

        request = Request()
        if proxies:
            request.session.proxies = proxies
        creds.refresh(request)
        with token_file.open("wb") as file_obj:
            pickle.dump(creds, file_obj)
        return creds

    if creds and creds.valid:
        return creds

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets), SCOPES)

    # 尝试多个端口
    ports_to_try = [port, 8080, 8090, 8888, 9000]
    last_error = None

    for try_port in ports_to_try:
        try:
            print(f"\n尝试使用端口 {try_port} 进行授权...")
            creds = flow.run_local_server(
                host="127.0.0.1",
                port=try_port,
                authorization_prompt_message=f"请在浏览器完成授权（端口{try_port}），完成后会自动返回。",
                success_message="授权完成，可以关闭此页面。",
                open_browser=True,
                access_type="offline",
                prompt="consent",
                include_granted_scopes="true",
            )
            print(f"授权成功！使用端口 {try_port}")
            break
        except Exception as e:
            last_error = e
            print(f"端口 {try_port} 失败: {e}")
            if try_port == ports_to_try[-1]:
                raise Exception(f"所有端口都失败了。最后错误: {last_error}")
            continue

    ensure_parent(token_file)
    with token_file.open("wb") as file_obj:
        pickle.dump(creds, file_obj)

    return creds


def build_clients(creds: Credentials):
    youtube = build("youtube", "v3", credentials=creds)
    analytics = build("youtubeAnalytics", "v2", credentials=creds)
    return youtube, analytics


def get_analytics_window(days: int = 28) -> tuple[date, date]:
    end_date = date.today() - timedelta(days=ANALYTICS_LAG_DAYS)
    start_date = end_date - timedelta(days=days - 1)
    return start_date, end_date


def get_current_channel(youtube) -> Dict:
    response = youtube.channels().list(part="snippet,statistics", mine=True, maxResults=1).execute()
    items = response.get("items", [])
    if not items:
        raise RuntimeError("当前授权没有返回频道信息，请确认你在授权时选择了正确的 YouTube 频道身份。")

    item = items[0]
    snippet = item.get("snippet", {})
    statistics = item.get("statistics", {})
    return {
        "channel_id": item.get("id", ""),
        "channel_title": snippet.get("title", ""),
        "custom_url": snippet.get("customUrl", ""),
        "subscriber_count": int(statistics.get("subscriberCount", 0) or 0),
        "video_count": int(statistics.get("videoCount", 0) or 0),
        "total_view_count": int(statistics.get("viewCount", 0) or 0),
    }


def get_analytics_summary(analytics) -> Dict:
    start_date, end_date = get_analytics_window(days=28)
    # 获取总收入（从2005-01-01至今）
    response_total = (
        analytics.reports()
        .query(
            ids="channel==MINE",
            startDate="2005-01-01",
            endDate=end_date.isoformat(),
            metrics="estimatedRevenue",
        )
        .execute()
    )
    total_revenue = float(response_total.get("rows", [[0]])[0][0] or 0) if response_total.get("rows") else 0.0

    # 获取28天数据
    response = (
        analytics.reports()
        .query(
            ids="channel==MINE",
            startDate=start_date.isoformat(),
            endDate=end_date.isoformat(),
            metrics="views,estimatedMinutesWatched,estimatedRevenue,playbackBasedCpm,monetizedPlaybacks",
        )
        .execute()
    )

    rows = response.get("rows", [])
    views = int(rows[0][0] or 0) if rows else 0
    watched_minutes = float(rows[0][1] or 0) if rows else 0.0
    revenue = float(rows[0][2] or 0) if rows else 0.0
    playback_based_cpm = float(rows[0][3] or 0) if rows else 0.0
    monetized_playbacks = int(rows[0][4] or 0) if rows and len(rows[0]) > 4 else 0

    # 使用货币化播放次数计算 RPM（更准确）
    rpm = round((revenue / monetized_playbacks * 1000), 2) if monetized_playbacks > 0 else 0.0

    return {
        "period_start": start_date.isoformat(),
        "period_end": end_date.isoformat(),
        "views_28d": views,
        "watch_hours_28d": round(watched_minutes / 60.0, 2),
        "estimated_revenue_28d_usd": round(revenue, 4),
        "estimated_revenue_total_usd": round(total_revenue, 4),
        "playback_based_cpm_28d_usd": round(playback_based_cpm, 4),
        "rpm_28d_usd": rpm,
    }


def get_views_48h(analytics) -> int:
    end_date = date.today() - timedelta(days=ANALYTICS_LAG_DAYS)
    start_date = end_date - timedelta(days=1)
    response = (
        analytics.reports()
        .query(
            ids="channel==MINE",
            startDate=start_date.isoformat(),
            endDate=end_date.isoformat(),
            metrics="views",
            dimensions="day",
            sort="day",
        )
        .execute()
    )
    rows = response.get("rows", [])
    return int(sum(int(row[1] or 0) for row in rows))


def read_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    return pd.read_excel(path)


def write_table(path: Path, data: pd.DataFrame) -> None:
    ensure_parent(path)

    # 只对输出文件（包含income的文件）进行中文列名转换
    if "income" in path.name.lower():
        output_data = data.copy()
        column_mapping = {
            "capture_time": "采集时间",
            "channel_title": "频道名称",
            "subscriber_count": "订阅数",
            "estimated_revenue_total_usd": "总收入-从始至终(美元)",
            "views_48h": "近48小时观看次数",
            "api_period": "数据周期",
        }
        output_data = output_data.rename(columns=column_mapping)
    else:
        output_data = data

    if path.suffix.lower() == ".csv":
        output_data.to_csv(path, index=False, encoding="utf-8-sig")
    else:
        output_data.to_excel(path, index=False)


def make_public_report(data: pd.DataFrame) -> pd.DataFrame:
    if data.empty:
        return data

    public_data = data.copy()
    if "period_start" in public_data.columns and "period_end" in public_data.columns:
        public_data["api_period"] = public_data["period_start"].astype(str) + " ~ " + public_data["period_end"].astype(str)

    if "channel_id" in public_data.columns:
        public_data = public_data.drop(columns=["channel_id"])

    preferred_columns = [
        "capture_time",
        "channel_title",
        "subscriber_count",
        "estimated_revenue_total_usd",
        "views_48h",
        "api_period",
    ]
    existing_columns = [column for column in preferred_columns if column in public_data.columns]
    return public_data[existing_columns]


def upsert_registry(registry_path: Path, row: Dict) -> None:
    registry = read_table(registry_path)
    if not registry.empty and "channel_id" in registry.columns:
        registry = registry[registry["channel_id"] != row["channel_id"]]
    registry = pd.concat([registry, pd.DataFrame([row])], ignore_index=True)
    registry = registry.sort_values(by=["updated_at", "channel_title"], ascending=[False, True])
    write_table(registry_path, registry)


def get_registry(registry_path: Path) -> pd.DataFrame:
    registry = read_table(registry_path)
    if registry.empty:
        return pd.DataFrame(columns=["updated_at", "alias", "channel_title", "channel_id", "custom_url", "token_file", "status"])
    return registry


def match_registry_row(registry: pd.DataFrame, identifier: str) -> pd.Series:
    if registry.empty:
        raise RuntimeError("当前还没有任何已登记频道。")

    identifier = identifier.strip()
    matched = registry[
        (registry["channel_id"].astype(str) == identifier)
        | (registry["channel_title"].astype(str) == identifier)
        | (registry["alias"].fillna("").astype(str) == identifier)
    ]
    if matched.empty:
        raise RuntimeError(f"未找到频道: {identifier}")
    if len(matched) > 1:
        raise RuntimeError(f"匹配到多个频道，请改用 channel_id: {identifier}")
    return matched.iloc[0]


def save_authorized_channel(
    client_secrets: Path,
    token_dir: Path,
    registry_path: Path,
    alias: Optional[str],
    force_reauth: bool,
    port: int,
) -> Dict:
    token_dir.mkdir(parents=True, exist_ok=True)
    temp_token = token_dir / "_pending_auth.pickle"
    creds = load_credentials(client_secrets, temp_token, force_reauth=True if force_reauth else temp_token.exists(), port=port)
    youtube, _ = build_clients(creds)
    channel = get_current_channel(youtube)

    base_name = alias.strip() if alias else channel["channel_title"]
    token_file = token_dir / f"{sanitize_name(base_name)}__{channel['channel_id']}.pickle"

    if token_file.exists():
        token_file.unlink()
    temp_token.replace(token_file)

    row = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "alias": alias or "",
        "channel_title": channel["channel_title"],
        "channel_id": channel["channel_id"],
        "custom_url": channel["custom_url"],
        "token_file": str(token_file),
        "status": "已授权",
    }
    upsert_registry(registry_path, row)
    return row


def collect_one_channel(client_secrets: Path, token_file: Path) -> Dict:
    creds = load_credentials(client_secrets, token_file, force_reauth=False, port=8765)
    youtube, analytics = build_clients(creds)
    channel = get_current_channel(youtube)

    # 重试3次
    for attempt in range(3):
        try:
            summary = get_analytics_summary(analytics)
            views_48h = get_views_48h(analytics)
            return {
                "capture_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                **channel,
                **summary,
                "views_48h": views_48h,
                "token_file": str(token_file),
                "status": "成功",
                "error": "",
            }
        except HttpError as e:
            status_code = e.resp.status if hasattr(e, 'resp') else 0
            # 403是权限问题，不重试
            if status_code == 403:
                error_msg = "未开通货币化"
                break
            # 500/503是服务器错误，重试
            if status_code in [500, 503] and attempt < 2:
                continue
            error_msg = f"API错误{status_code}"
            break

    # 返回基本信息
    return {
        "capture_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        **channel,
        "period_start": "",
        "period_end": "",
        "views_28d": 0,
        "watch_hours_28d": 0.0,
        "estimated_revenue_28d_usd": 0.0,
        "estimated_revenue_total_usd": 0.0,
        "playback_based_cpm_28d_usd": 0.0,
        "rpm_28d_usd": 0.0,
        "views_48h": 0,
        "token_file": str(token_file),
        "status": error_msg,
        "error": str(status_code),
    }


def collect_one_channel_safe(client_secrets: Path, token_file: Path) -> Dict:
    fallback_channel = {
        "channel_id": "",
        "channel_title": token_file.stem.split("__")[0],
        "custom_url": "",
        "subscriber_count": 0,
        "video_count": 0,
        "total_view_count": 0,
    }
    try:
        return collect_one_channel(client_secrets, token_file)
    except RefreshError as exc:
        return {
            "capture_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            **fallback_channel,
            "period_start": "",
            "period_end": "",
            "views_28d": 0,
            "watch_hours_28d": 0.0,
            "estimated_revenue_28d_usd": 0.0,
            "estimated_revenue_total_usd": 0.0,
            "playback_based_cpm_28d_usd": 0.0,
            "rpm_28d_usd": 0.0,
            "views_48h": 0,
            "token_file": str(token_file),
            "status": "令牌失效",
            "error": str(exc),
        }
    except (TimeoutError, OSError, RequestException) as exc:
        return {
            "capture_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            **fallback_channel,
            "period_start": "",
            "period_end": "",
            "views_28d": 0,
            "watch_hours_28d": 0.0,
            "estimated_revenue_28d_usd": 0.0,
            "estimated_revenue_total_usd": 0.0,
            "playback_based_cpm_28d_usd": 0.0,
            "rpm_28d_usd": 0.0,
            "views_48h": 0,
            "token_file": str(token_file),
            "status": "网络超时",
            "error": repr(exc),
        }


def collect_all_channels(client_secrets: Path, token_dir: Path, registry_path: Path, output_path: Path, progress_callback=None) -> pd.DataFrame:
    rows: List[Dict] = []
    registry = get_registry(registry_path)

    if registry.empty:
        # 返回空的DataFrame，但包含所有必需的列
        empty_df = pd.DataFrame(columns=[
            "capture_time", "channel_title", "subscriber_count",
            "estimated_revenue_total_usd", "views_48h", "api_period"
        ])
        write_table(output_path, empty_df)
        return empty_df

    active_registry = registry[registry["status"].fillna("").astype(str) == "已授权"].copy()
    token_files = [Path(value) for value in active_registry["token_file"].tolist() if str(value).strip()]
    total = len(token_files)

    for idx, token_file in enumerate(token_files, 1):
        if progress_callback:
            progress_callback(idx, total)
        if token_file.name.startswith("_pending_") or not token_file.exists():
            rows.append(
                {
                    "capture_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "channel_title": "",
                    "channel_id": "",
                    "token_file": str(token_file),
                    "status": "令牌缺失",
                    "error": "token file not found",
                }
            )
            continue
        try:
            rows.append(collect_one_channel_safe(client_secrets, token_file))
        except HttpError as exc:
            rows.append(
                {
                    "capture_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "channel_title": "",
                    "channel_id": "",
                    "token_file": str(token_file),
                    "status": "http_error",
                    "error": exc.content.decode("utf-8", errors="ignore"),
                }
            )
        except Exception as exc:
            rows.append(
                {
                    "capture_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "channel_title": "",
                    "channel_id": "",
                    "token_file": str(token_file),
                    "status": "错误",
                    "error": repr(exc),
                }
            )

    result = pd.DataFrame(rows)
    if not result.empty:
        result = result.sort_values(by=["status", "channel_title"], ascending=[True, True])
    write_table(output_path, make_public_report(result))
    return result


def disable_channel(registry_path: Path, identifier: str, move_token: bool, inactive_dir: Path) -> Dict:
    registry = get_registry(registry_path)
    row = match_registry_row(registry, identifier)
    channel_id = row["channel_id"]
    token_file = Path(str(row["token_file"]))

    # 直接删除记录
    registry = registry[registry["channel_id"].astype(str) != str(channel_id)]

    if move_token and token_file.exists():
        inactive_dir.mkdir(parents=True, exist_ok=True)
        target = inactive_dir / token_file.name
        if target.exists():
            target.unlink()
        token_file.replace(target)

    write_table(registry_path, registry)
    return {
        "channel_id": str(channel_id),
        "channel_title": str(row["channel_title"]),
        "status": "disabled",
    }


def list_channels(registry_path: Path) -> pd.DataFrame:
    registry = get_registry(registry_path)
    if registry.empty:
        return registry
    return registry.sort_values(by=["status", "updated_at", "channel_title"], ascending=[True, False, True])


def export_chinese_report(source_path: Path, output_path: Path) -> Path:
    df = read_table(source_path)
    if df.empty:
        write_table(output_path, pd.DataFrame(columns=["频道名称", "订阅量", "收入(近28天USD)", "观看次数(API近28天)", "API数据区间", "采集时间"]))
        return output_path

    rename_map = {
        "channel_title": "频道名称",
        "subscriber_count": "订阅量",
        "estimated_revenue_total_usd": "总收入(USD)",
        "estimated_revenue_28d_usd": "收入(近28天USD)",
        "views_28d": "观看次数(API近28天)",
        "rpm_28d_usd": "RPM(近28天USD)",
        "api_period": "API数据区间",
        "capture_time": "采集时间",
    }
    columns = [
        "channel_title",
        "subscriber_count",
        "estimated_revenue_total_usd",
        "estimated_revenue_28d_usd",
        "views_28d",
        "rpm_28d_usd",
        "api_period",
        "capture_time",
    ]
    source = make_public_report(df)
    data = source[columns].rename(columns=rename_map)
    write_table(output_path, data)
    return output_path


def parse_args() -> argparse.Namespace:
    defaults = get_default_paths()
    default_root = defaults["root"]
    default_client = defaults["client_secrets"]
    default_token_dir = defaults["token_dir"]
    default_registry = defaults["registry"]
    default_output = defaults["output"]

    parser = argparse.ArgumentParser(description="不用 CMS 的多频道 YouTube 收益采集工具")
    parser.add_argument("--client-secrets", default=str(default_client), help="Google OAuth client secrets JSON 路径")

    subparsers = parser.add_subparsers(dest="command", required=True)

    auth_parser = subparsers.add_parser("authorize", help="为当前登录的频道授权并保存独立 token")
    auth_parser.add_argument("--token-dir", default=str(default_token_dir), help="token 存放目录")
    auth_parser.add_argument("--registry", default=str(default_registry), help="已授权频道登记表")
    auth_parser.add_argument("--alias", default="", help="给当前频道取一个便于识别的别名")
    auth_parser.add_argument("--force-reauth", action="store_true", help="强制重新授权")
    auth_parser.add_argument("--port", type=int, default=8765, help="本地 OAuth 回调端口")

    collect_parser = subparsers.add_parser("collect", help="遍历全部 token 批量采集频道收益数据")
    collect_parser.add_argument("--token-dir", default=str(default_token_dir), help="token 存放目录")
    collect_parser.add_argument("--registry", default=str(default_registry), help="已授权频道登记表")
    collect_parser.add_argument("--output", default=str(default_output), help="汇总输出文件，支持 xlsx/csv")

    list_parser = subparsers.add_parser("list", help="查看当前已登记频道")
    list_parser.add_argument("--registry", default=str(default_registry), help="已授权频道登记表")

    disable_parser = subparsers.add_parser("disable", help="停用某个频道并在采集时跳过")
    disable_parser.add_argument("identifier", help="channel_id、channel_title 或 alias")
    disable_parser.add_argument("--registry", default=str(default_registry), help="已授权频道登记表")
    disable_parser.add_argument("--move-token", action="store_true", help="把 token 移到 inactive 目录")
    disable_parser.add_argument(
        "--inactive-dir",
        default=str(default_root / "tokens_inactive"),
        help="停用 token 的存放目录",
    )

    return parser.parse_args()


def main() -> None:
    setup_stdout()
    args = parse_args()
    client_secrets = Path(args.client_secrets)
    if not client_secrets.exists():
        raise FileNotFoundError(f"找不到 OAuth 凭证文件: {client_secrets}")

    if args.command == "authorize":
        row = save_authorized_channel(
            client_secrets=client_secrets,
            token_dir=Path(args.token_dir),
            registry_path=Path(args.registry),
            alias=args.alias or None,
            force_reauth=args.force_reauth,
            port=args.port,
        )
        print("CHANNEL_AUTHORIZED=TRUE")
        print(f"CHANNEL_TITLE={row['channel_title']}")
        print(f"CHANNEL_ID={row['channel_id']}")
        print(f"TOKEN_FILE={row['token_file']}")
        print(f"REGISTRY={args.registry}")
        return

    if args.command == "collect":
        result = collect_all_channels(
            client_secrets=client_secrets,
            token_dir=Path(args.token_dir),
            registry_path=Path(args.registry),
            output_path=Path(args.output),
        )
        print(f"COLLECTED_COUNT={len(result)}")
        print(f"OUTPUT={args.output}")
        if not result.empty:
            ok_count = int((result["status"] == "ok").sum())
            print(f"SUCCESS_COUNT={ok_count}")
            print(f"FAILED_COUNT={len(result) - ok_count}")
        return

    if args.command == "list":
        registry = list_channels(Path(args.registry))
        print(f"CHANNEL_COUNT={len(registry)}")
        if not registry.empty:
            print(registry[["channel_title", "channel_id", "alias", "status", "updated_at"]].to_string(index=False))
        return

    if args.command == "disable":
        result = disable_channel(
            registry_path=Path(args.registry),
            identifier=args.identifier,
            move_token=args.move_token,
            inactive_dir=Path(args.inactive_dir),
        )
        print("CHANNEL_DISABLED=TRUE")
        print(f"CHANNEL_TITLE={result['channel_title']}")
        print(f"CHANNEL_ID={result['channel_id']}")
        return


if __name__ == "__main__":
    main()
