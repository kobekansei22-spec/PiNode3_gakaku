"""
データ収集のメインスクリプト

センサ値・収集状態・画像を取得し、以下の2経路に送信する（並行稼働）:
  - S3   : センサJSONを直接PUT（新・本命の経路）
  - MQTT : IoT Core経由でDynamoDBへ（既存・当面残す）

S3側が安定して動作することを確認できたら、MQTT送信は削除してよい。
"""
from datetime import datetime, timezone

from sensor import Sensor
from camera import Camera
from mqtt_client import MQTTClient
from s3_uploader import S3Uploader

import util


def build_payload(timestamp, values, status, image_keys, wilt_device=None):
    """S3にもMQTTにも送る共通のペイロードを組み立てる"""
    config     = util.get_pinode_config()
    iot_config = config["aws_iot"]

    payload = {
        "deviceID":     config["device_id"],
        "fieldID":      iot_config["field_id"],
        "projectID":    iot_config["project_id"],
        "deviceType":   iot_config.get("device_type", "PiNode"),
        "timestamp":    timestamp,
        # センサ値はトップレベルに展開（DynamoDBでの検索・整合のため）
        **values,
    }
    if status:
        payload["sensorStatus"] = status
    if image_keys:
        payload["imageKeys"] = image_keys
    if wilt_device:
        payload["wiltDeviceId"] = wilt_device
    return payload


if __name__ == "__main__":
    config      = util.get_pinode_config()
    wilt_device = config["aws_iot"].get("wilt_device_id")
    
    # 1. センサーデータ取得 + 収集状態の取得 + CSV保存
    #    （センサ取得を一度だけ行い、値と状態を同時に得る）
    sensor = Sensor()
    df, sensor_timestamp, values, status = sensor.upload_csv_with_status()

    # 2. 画像撮影 + ローカル保存
    saved_paths = Camera().save_images() or []

    # 3. 画像をS3にアップロード
    uploader = S3Uploader()
    s3_keys = uploader.upload_images(saved_paths) if saved_paths else []

    # 4. 送信するペイロードを組み立て
    payload = build_payload(
        timestamp  = sensor_timestamp,
        values     = values,
        status     = status,
        image_keys = s3_keys if s3_keys else None,
        wilt_device = wilt_device,
    )

    # 5-A. 【新・本命】センサJSONをS3に直接PUT
    uploader.upload_sensor_json(payload, timestamp=sensor_timestamp)

    # 5-B. 【既存・当面残す】MQTT経由でDynamoDBへ送信
    #      S3側が安定したら、この2行を削除してよい
    MQTTClient().publish_sensor(
        sensor_data   = values,
        timestamp     = sensor_timestamp,
        image_keys    = s3_keys if s3_keys else None,
        sensor_status = status,
    )