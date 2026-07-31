"""
IoT証明書でS3にデータをアップロードするクラス
アクセスキー不要でIoT Credentials Providerを使用する

- 画像:      upload_image / upload_images
- センサJSON: upload_sensor_json   ← 追加
"""
import boto3
import json
import os
import ssl
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
import util

CERT_DIR   = '/etc/iot'
ROLE_ALIAS = 'AgriDeviceSecretsAlias'
REGION     = 'ap-northeast-1'


class S3Uploader:
    """
    IoT証明書でS3にデータをアップロードするクラス

    Notes:
        config.json に以下の設定が必要:
        {
            "aws_iot": {
                "credentials_endpoint": "xxxx.credentials.iot.ap-northeast-1.amazonaws.com",
                "project_id": "daiwa",
                "field_id": "8"
            },
            "s3": {
                "bucket_name": "agri-data-bucket"
            }
        }
    """
    def __init__(self):
        config               = util.get_pinode_config()
        iot_config           = config["aws_iot"]
        self.device_id       = config["device_id"]
        self.project_id      = iot_config["project_id"]
        self.field_id        = iot_config["field_id"]
        self.credentials_ep  = iot_config["credentials_endpoint"]
        self.bucket          = config["s3"]["bucket_name"]
        self._s3_client      = None  # 遅延初期化（接続時に作成）

    def _get_temp_credentials(self) -> dict:
        """IoT証明書で一時IAMトークンを取得"""
        url = f'https://{self.credentials_ep}/role-aliases/{ROLE_ALIAS}/credentials'

        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.load_verify_locations(f'{CERT_DIR}/root-CA.pem')
        ctx.load_cert_chain(f'{CERT_DIR}/cert.pem', f'{CERT_DIR}/private.key')

        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, context=ctx) as res:
            return json.loads(res.read())['credentials']

    def _get_s3_client(self):
        """一時トークンでS3クライアントを作成"""
        if self._s3_client is None:
            creds = self._get_temp_credentials()
            self._s3_client = boto3.client(
                's3',
                region_name           = REGION,
                aws_access_key_id     = creds['accessKeyId'],
                aws_secret_access_key = creds['secretAccessKey'],
                aws_session_token     = creds['sessionToken'],
            )
        return self._s3_client

    # ─────────────────────────────────────────────────────
    # 画像アップロード（既存）
    # ─────────────────────────────────────────────────────
    def upload_image(self, local_path: str) -> str | None:
        """
        画像ファイルをS3にアップロードする

        Args:
            local_path: ローカルファイルパス

        Returns:
            s3Key（成功時）またはNone（失敗時）
        """
        local_path = Path(local_path)
        if not local_path.exists():
            print(f"ファイルが見つかりません: {local_path}")
            return None

        # S3キーの構築
        # {projectID}/{fieldID}/{deviceID}/images/{filename}
        s3_key = f"{self.project_id}/{self.field_id}/{self.device_id}/images/{local_path.name}"

        # content_typeの判定
        suffix = local_path.suffix.lower()
        content_type = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
        }.get(suffix, 'application/octet-stream')

        try:
            s3 = self._get_s3_client()
            s3.upload_file(
                str(local_path),
                self.bucket,
                s3_key,
                ExtraArgs={'ContentType': content_type}
            )
            print(f"S3アップロード完了: {local_path.name} → s3://{self.bucket}/{s3_key}")
            return s3_key
        except Exception as e:
            print(f"S3アップロードエラー ({local_path.name}): {e}")
            return None

    def upload_images(self, local_paths: list[str]) -> list[str]:
        """
        複数の画像ファイルをS3にアップロードする

        Args:
            local_paths: ローカルファイルパスのリスト

        Returns:
            アップロード成功したs3Keyのリスト
        """
        if not local_paths:
            return []

        s3_keys = []
        for path in local_paths:
            s3_key = self.upload_image(path)
            if s3_key:
                s3_keys.append(s3_key)

        print(f"S3アップロード: {len(s3_keys)}/{len(local_paths)}件 成功")
        return s3_keys

    # ─────────────────────────────────────────────────────
    # センサJSONアップロード（追加）
    # ─────────────────────────────────────────────────────
    def upload_sensor_json(self, payload: dict, timestamp: str = None) -> str | None:
        """
        センサデータをJSONファイルとしてS3にアップロードする

        Args:
            payload:   送信するセンサデータの辞書
                       例: {"deviceID": ..., "timestamp": ...,
                            "temperature": 34.2, ...,
                            "sensorStatus": {...}, "imageKeys": [...]}
            timestamp: ファイル名に使う時刻（ISO8601）。省略時は現在時刻。

        Returns:
            s3Key（成功時）またはNone（失敗時）

        Notes:
            S3キー構造:
              {projectID}/{fieldID}/{deviceID}/sensors/{timestamp}.json
            例:
              daiwa/8/PiNode39/sensors/2026-07-27T164500+0900.json

            画像と同じ一時トークンの仕組み（_get_s3_client）を使う。
            ファイル名にコロン(:)は使えないため、時刻からコロンを除去する。
        """
        ts = timestamp if timestamp else datetime.now(timezone.utc).astimezone().isoformat()

        # S3キーに使えるようにコロン等を除去（ファイル名として安全な形に）
        safe_ts = ts.replace(":", "").replace("+", "plus")

        s3_key = f"{self.project_id}/{self.field_id}/{self.device_id}/sensors/{safe_ts}.json"

        try:
            s3 = self._get_s3_client()
            body = json.dumps(payload, ensure_ascii=False, indent=2)
            s3.put_object(
                Bucket      = self.bucket,
                Key         = s3_key,
                Body        = body.encode("utf-8"),
                ContentType = "application/json",
            )
            print(f"S3センサJSON送信完了: → s3://{self.bucket}/{s3_key}")
            return s3_key
        except Exception as e:
            print(f"S3センサJSON送信エラー: {e}")
            return None