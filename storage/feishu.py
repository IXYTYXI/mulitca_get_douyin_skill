import httpx
import math
import os
import zlib
from typing import List, Optional
from config.settings import (
    FEISHU_APP_ID,
    FEISHU_APP_SECRET,
    FEISHU_APP_TOKEN,
    FEISHU_TABLE_ID,
    FEISHU_API_BASE,
)


class FeishuBitable:
    """Write data to Feishu multidimensional tables (Bitable)."""

    def __init__(
        self,
        app_id: str = "",
        app_secret: str = "",
        app_token: str = "",
        table_id: str = "",
    ):
        self.app_id = app_id or FEISHU_APP_ID
        self.app_secret = app_secret or FEISHU_APP_SECRET
        self.app_token = app_token or FEISHU_APP_TOKEN
        self.table_id = table_id or FEISHU_TABLE_ID
        self._tenant_token: str = ""
        self._client = httpx.Client(timeout=30.0)

    def _get_tenant_token(self) -> str:
        if self._tenant_token:
            return self._tenant_token
        url = f"{FEISHU_API_BASE}/auth/v3/tenant_access_token/internal"
        resp = self._client.post(
            url,
            json={"app_id": self.app_id, "app_secret": self.app_secret},
        )
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(
                f"Failed to get Feishu token: {data.get('msg', 'unknown error')}"
            )
        self._tenant_token = data["tenant_access_token"]
        return self._tenant_token

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._get_tenant_token()}",
            "Content-Type": "application/json; charset=utf-8",
        }

    def create_app(self, name: str, folder_token: str = "") -> dict:
        """Create a NEW Bitable app (multidimensional table file).

        ``folder_token`` places the new file inside a Drive folder (the app must
        be a collaborator with edit rights on that folder, otherwise Feishu
        returns ``DriveNodePermNotAllow``). Empty ``folder_token`` creates it in
        the app's own space.

        On success sets ``self.app_token`` to the new app and returns the app
        info dict: ``{app_token, default_table_id, url, name, ...}``.
        """
        url = f"{FEISHU_API_BASE}/bitable/v1/apps"
        body = {"name": name}
        if folder_token:
            body["folder_token"] = folder_token
        resp = self._client.post(url, headers=self._headers(), json=body)
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(
                f"Failed to create bitable app: code={data.get('code')} "
                f"msg={data.get('msg')}"
            )
        app = data["data"]["app"]
        self.app_token = app["app_token"]
        print(f"[Feishu] Created bitable '{name}': {app.get('url', self.app_token)}")
        return app

    def delete_app(self, app_token: str = "") -> bool:
        """Delete a Bitable app via the Drive files API."""
        at = app_token or self.app_token
        url = f"{FEISHU_API_BASE}/drive/v1/files/{at}"
        resp = self._client.delete(
            url,
            headers={"Authorization": f"Bearer {self._get_tenant_token()}"},
            params={"type": "bitable"},
        )
        return resp.json().get("code") == 0

    def list_tables(self) -> list:
        """List all tables in the Bitable app."""
        url = f"{FEISHU_API_BASE}/bitable/v1/apps/{self.app_token}/tables"
        resp = self._client.get(url, headers=self._headers())
        data = resp.json()
        if data.get("code") != 0:
            print(f"[Feishu] List tables error: {data.get('msg')}")
            return []
        return data.get("data", {}).get("items", [])

    def create_table(self, name: str) -> str:
        """Create a new table and return its table_id."""
        url = f"{FEISHU_API_BASE}/bitable/v1/apps/{self.app_token}/tables"
        resp = self._client.post(
            url,
            headers=self._headers(),
            json={"table": {"name": name}},
        )
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"Failed to create table: {data.get('msg')}")
        table_id = data["data"]["table_id"]
        print(f"[Feishu] Created table '{name}' with ID: {table_id}")
        return table_id

    def add_fields(self, fields: List[dict], table_id: str = "") -> None:
        """
        Add fields to a table.
        Each field: {"field_name": "xxx", "type": 1}
        Types: 1=text, 2=number, 3=select, 5=datetime, 7=checkbox, 15=link, 17=attachment
        """
        tid = table_id or self.table_id
        for f in fields:
            url = f"{FEISHU_API_BASE}/bitable/v1/apps/{self.app_token}/tables/{tid}/fields"
            resp = self._client.post(url, headers=self._headers(), json=f)
            data = resp.json()
            if data.get("code") != 0:
                print(f"[Feishu] Add field '{f.get('field_name')}' error: {data.get('msg')}")

    def write_records(
        self, records: List[dict], table_id: str = ""
    ) -> int:
        """
        Batch write records to a table. Max 500 per batch.
        Each record is a dict of {field_name: value}.
        Returns number of records written.
        """
        tid = table_id or self.table_id
        total_written = 0

        for i in range(0, len(records), 500):
            batch = records[i : i + 500]
            url = (
                f"{FEISHU_API_BASE}/bitable/v1/apps/{self.app_token}"
                f"/tables/{tid}/records/batch_create"
            )
            payload = {"records": [{"fields": r} for r in batch]}
            resp = self._client.post(
                url, headers=self._headers(), json=payload
            )
            data = resp.json()
            if data.get("code") != 0:
                print(
                    f"[Feishu] Batch write error (batch {i // 500 + 1}): "
                    f"{data.get('msg')}"
                )
            else:
                written = len(data.get("data", {}).get("records", []))
                total_written += written

        print(f"[Feishu] Written {total_written}/{len(records)} records to table {tid}")
        return total_written

    def setup_video_table(self, table_id: str = "") -> None:
        """Create fields for the video data table."""
        fields = [
            {"field_name": "作者", "type": 1},
            {"field_name": "作品正文", "type": 1},
            {"field_name": "作品链接", "type": 15},
            {"field_name": "作品封面", "type": 15},
            {"field_name": "作品图片", "type": 1},
            {"field_name": "作品视频", "type": 15},
            {"field_name": "点赞数", "type": 2},
            {"field_name": "评论数", "type": 2},
            {"field_name": "收藏数", "type": 2},
            {"field_name": "分享数", "type": 2},
            {"field_name": "播放量", "type": 2},
            {"field_name": "发布时间", "type": 1},
            {"field_name": "话题标签", "type": 1},
            {"field_name": "作者主页", "type": 15},
        ]
        self.add_fields(fields, table_id)

    def setup_user_table(self, table_id: str = "") -> None:
        """Create fields for the user data table."""
        fields = [
            {"field_name": "用户ID", "type": 1},
            {"field_name": "昵称", "type": 1},
            {"field_name": "简介", "type": 1},
            {"field_name": "粉丝数", "type": 2},
            {"field_name": "关注数", "type": 2},
            {"field_name": "获赞数", "type": 2},
            {"field_name": "作品数", "type": 2},
            {"field_name": "主页链接", "type": 15},
        ]
        self.add_fields(fields, table_id)

    def setup_comment_table(self, table_id: str = "") -> None:
        """Create fields for the comment data table."""
        fields = [
            {"field_name": "评论ID", "type": 1},
            {"field_name": "视频ID", "type": 1},
            {"field_name": "评论内容", "type": 1},
            {"field_name": "用户昵称", "type": 1},
            {"field_name": "用户ID", "type": 1},
            {"field_name": "点赞数", "type": 2},
            {"field_name": "回复数", "type": 2},
            {"field_name": "发布时间", "type": 1},
        ]
        self.add_fields(fields, table_id)

    def setup_trending_table(self, table_id: str = "") -> None:
        """Create fields for the trending data table."""
        fields = [
            {"field_name": "排名", "type": 2},
            {"field_name": "热搜词", "type": 1},
            {"field_name": "热度值", "type": 2},
            {"field_name": "标签", "type": 1},
            {"field_name": "视频数", "type": 2},
        ]
        self.add_fields(fields, table_id)

    def close(self):
        self._client.close()

    def delete_all_records(self, table_id: str = "") -> int:
        tid = table_id or self.table_id
        total_deleted = 0
        while True:
            url = f"{FEISHU_API_BASE}/bitable/v1/apps/{self.app_token}/tables/{tid}/records"
            resp = self._client.get(url, headers=self._headers(), params={"page_size": 500})
            data = resp.json()
            items = data.get("data", {}).get("items", [])
            if not items:
                break
            record_ids = [item["record_id"] for item in items]
            del_url = f"{FEISHU_API_BASE}/bitable/v1/apps/{self.app_token}/tables/{tid}/records/batch_delete"
            self._client.post(del_url, headers=self._headers(), json={"records": record_ids})
            total_deleted += len(record_ids)
        print(f"[Feishu] Deleted {total_deleted} records from table {tid}")
        return total_deleted

    def upload_file(self, file_path: str, parent_type: str = "bitable_image") -> str:
        """Upload a file to Feishu. Returns file_token. Uses chunked upload for files > 20MB."""
        file_size = os.path.getsize(file_path)
        file_name = os.path.basename(file_path)
        token = self._get_tenant_token()

        if file_size <= 20 * 1024 * 1024:
            return self._upload_small(file_path, file_name, file_size, parent_type, token)
        else:
            return self._upload_chunked(file_path, file_name, file_size, parent_type, token)

    def _upload_small(self, file_path, file_name, file_size, parent_type, token):
        headers = {"Authorization": f"Bearer {token}"}
        with open(file_path, "rb") as f:
            resp = self._client.post(
                f"{FEISHU_API_BASE}/drive/v1/medias/upload_all",
                headers=headers,
                data={
                    "file_name": file_name,
                    "parent_type": parent_type,
                    "parent_node": self.app_token,
                    "size": str(file_size),
                },
                files={"file": (file_name, f, "application/octet-stream")},
            )
        data = resp.json()
        if data.get("code") != 0:
            print(f"[Feishu] Upload error: {data.get('msg')}")
            return ""
        return data.get("data", {}).get("file_token", "")

    def _upload_chunked(self, file_path, file_name, file_size, parent_type, token):
        headers_json = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        headers_upload = {"Authorization": f"Bearer {token}"}

        resp = self._client.post(
            f"{FEISHU_API_BASE}/drive/v1/medias/upload_prepare",
            headers=headers_json,
            json={
                "file_name": file_name,
                "parent_type": parent_type,
                "parent_node": self.app_token,
                "size": file_size,
            },
        )
        data = resp.json()
        if data.get("code") != 0:
            print(f"[Feishu] Upload prepare error: {data.get('msg')}")
            return ""

        upload_id = data["data"]["upload_id"]
        block_size = data["data"]["block_size"]
        block_num = data["data"]["block_num"]

        with open(file_path, "rb") as f:
            for i in range(block_num):
                chunk = f.read(block_size)
                if not chunk:
                    break
                checksum = str(zlib.adler32(chunk) & 0xFFFFFFFF)
                resp = self._client.post(
                    f"{FEISHU_API_BASE}/drive/v1/medias/upload_part",
                    headers=headers_upload,
                    data={
                        "upload_id": upload_id,
                        "seq": str(i),
                        "size": str(len(chunk)),
                        "checksum": checksum,
                    },
                    files={"file": (f"part_{i}", chunk, "application/octet-stream")},
                    timeout=120.0,
                )
                d = resp.json()
                if d.get("code") != 0:
                    print(f"[Feishu] Upload part {i} error: {d.get('msg')}")
                    return ""

        resp = self._client.post(
            f"{FEISHU_API_BASE}/drive/v1/medias/upload_finish",
            headers=headers_json,
            json={"upload_id": upload_id, "block_num": block_num},
        )
        data = resp.json()
        if data.get("code") != 0:
            print(f"[Feishu] Upload finish error: {data.get('msg')}")
            return ""
        return data.get("data", {}).get("file_token", "")


def video_to_feishu_record(video) -> dict:
    author_sec_uid = getattr(video, "author_sec_uid", "")
    return {
        "作者": video.author_nickname,
        "作品正文": video.desc,
        "作品链接": {"link": video.post_url, "text": "查看作品"} if video.post_url else "",
        "作品封面": {"link": video.cover_url, "text": "封面"} if video.cover_url else "",
        "作品图片": video.image_urls if video.image_urls else "",
        "作品视频": {"link": video.video_url, "text": "播放视频"} if video.video_url else "",
        "点赞数": video.digg_count,
        "评论数": video.comment_count,
        "收藏数": video.collect_count,
        "分享数": video.share_count,
        "播放量": video.play_count,
        "发布时间": video.create_time,
        "话题标签": video.hashtags,
        "作者主页": {"link": f"https://www.douyin.com/user/{author_sec_uid}", "text": video.author_nickname} if author_sec_uid else "",
    }


def user_to_feishu_record(user) -> dict:
    return {
        "用户ID": user.uid,
        "昵称": user.nickname,
        "简介": user.signature,
        "粉丝数": user.follower_count,
        "关注数": user.following_count,
        "获赞数": user.total_favorited,
        "作品数": user.aweme_count,
        "主页链接": {"link": user.homepage_url, "text": user.nickname} if user.homepage_url else "",
    }


def comment_to_feishu_record(comment) -> dict:
    return {
        "评论ID": comment.comment_id,
        "视频ID": comment.aweme_id,
        "评论内容": comment.text,
        "用户昵称": comment.user_nickname,
        "用户ID": comment.user_uid,
        "点赞数": comment.digg_count,
        "回复数": comment.reply_count,
        "发布时间": comment.create_time,
    }


def trending_to_feishu_record(item) -> dict:
    return {
        "排名": item.rank,
        "热搜词": item.title,
        "热度值": item.hot_value,
        "标签": item.label,
        "视频数": item.video_count,
    }
