"""
AWS IoT Core への MQTT 送信クライアント（awsiotsdk v2 対応）
config.json の設定を使用する
"""
from awscrt import mqtt
from awsiot import mqtt_connection_builder
from datetime import datetime, timezone
from pathlib import Path
import json
import util


class MQTTClient:
    """
    AWS IoT Core への MQTT 送信クライアント

    Notes:
        config.json に以下の設定が必要:
        {
            "device_id": "PiNode36",
            "aws_iot": {
                "endpoint":    "xxxx.iot.ap-northeast-1.amazonaws.com",
                "cert_dir":    "/etc/iot",
                "field_id":    "8",
                "project_id":  "daiwa",
                "device_type": "PiNode"
            }
        }
    """
    def __init__(self):
        config     = util.get_pinode_config()
        iot_config = config["aws_iot"]

        self.device_id   = config["device_id"]
        self.field_id    = iot_config["field_id"]
        self.project_id  = iot_config["project_id"]
        self.device_type = iot_config.get("device_type", "PiNode")
        self.topic       = f"agri/sensors/{self.device_id}/data"

        cert_dir = Path(iot_config["cert_dir"])

        # MQTT接続を構築（MTLSで証明書認証）
        self._connection = mqtt_connection_builder.mtls_from_path(
            endpoint         = iot_config["endpoint"],
            cert_filepath    = str(cert_dir / "cert.pem"),
            pri_key_filepath = str(cert_dir / "private.key"),
            ca_filepath      = str(cert_dir / "root-CA.pem"),
            client_id        = self.device_id,
            clean_session    = False,
            keep_alive_secs  = 30,
        )

    def publish_sensor(self, sensor_data: dict, timestamp: str = None,
                       image_keys: list = None, sensor_status: dict = None):
        """
        センサーデータを MQTT で送信する

        Args:
            sensor_data (dict): センサー値の辞書
                例: {"temperature": 25.5, "humidity": 60.0, ...}
            timestamp (str): 収集時刻（ISO8601）。省略時は送信時刻を付与
            image_keys (list): S3に保存した画像のキー一覧（省略可）
            sensor_status (dict): センサ名 -> 収集状態（省略可）
                例: {"temperature": {"result": "SUCCESS",
                                     "retry_count": 0,
                                     "is_fallback": False}, ...}

        Notes:
            - センサ値(temperature等)はトップレベルに展開する。
              → DynamoDBで各値が独立カラムになり、検索・フィルタしやすい。
            - 収集状態(sensorStatus)は1つのMapにまとめて付与する。
              → 検索対象ではなく付随情報のため、カラムを増やさない。
            - PK: deviceID / SK: timestamp はトップレベルに置く。
        """
        payload = {
            "deviceID":     self.device_id,
            "fieldID":      self.field_id,
            "projectID":    self.project_id,
            "deviceType":   self.device_type,
            "timestamp":    timestamp if timestamp else datetime.now(timezone.utc).astimezone().isoformat(),
            # センサ値はトップレベルに展開（検索用）
            **sensor_data,
        }
        # 収集状態はまとめて1カラムに（付随情報）
        if sensor_status:
            payload["sensorStatus"] = sensor_status
        if image_keys:
            payload["imageKeys"] = image_keys

        connected = False
        try:
            # 接続
            connect_future = self._connection.connect()
            connect_future.result()
            connected = True

            # 送信
            publish_future, _ = self._connection.publish(
                topic   = self.topic,
                payload = json.dumps(payload),
                qos     = mqtt.QoS.AT_LEAST_ONCE,
            )
            publish_future.result()
            print(f"MQTT送信完了: {payload['timestamp']}")

        except Exception as e:
            print(f"MQTT送信エラー: {e}")

        finally:
            # 接続済みの場合のみ切断
            # 未接続時にdisconnectを呼ぶとクラッシュするため必ずフラグで判定する
            if connected:
                try:
                    disconnect_future = self._connection.disconnect()
                    disconnect_future.result()
                except Exception:
                    pass