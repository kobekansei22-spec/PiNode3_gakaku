import json
import time
import pandas as pd
from enum import Enum
from pathlib import Path
from datetime import datetime, timezone
import read_sensor
import util
from db import InfluxDB


class SensorResult(Enum):
    """
    センサデータの状態を表す列挙型

    Notes:
        SUCCESS             = 0  : 正常
        EMPTY_STRING_ERROR  = 1  : 空文字エラー
        NAN_ERROR           = 2  : nanエラー
        INF_ERROR           = 3  : infエラー
        MIN_VALUE_ERROR     = 4  : 最小値エラー
        MAX_VALUE_ERROR     = 5  : 最大値エラー
    """
    SUCCESS             = 0
    EMPTY_STRING_ERROR  = 1
    NAN_ERROR           = 2
    INF_ERROR           = 3
    MIN_VALUE_ERROR     = 4
    MAX_VALUE_ERROR     = 5


class Sensor:
    """
    センサからの情報取得を行うクラス
    """
    # センサ名
    TEMP   = "temperature"
    HD     = "humidity"
    I_LX   = "i_v_light"
    U_LX   = "u_v_light"
    TEMPHQ = "temperature_hq"
    HDHQ   = "humidity_hq"
    STEM   = "stem"
    FRUIT  = "fruit_diagram"

    def __init__(self):
        """
        センサクラスの初期化メソッド

        Notes:
            設定ファイルと前回のセンサデータを読み込む
        """
        # 設定ファイルの読み込み
        self.config = util.get_pinode_config()
        # 前回のセンサデータパス
        self.previous_data_path = self.config['sensor']['previous_data_path']
        self.sensor_manager = read_sensor.SensorManager()

        # 前回のセンサデータを読み込む
        with open(self.previous_data_path, "r") as f:
            self.previous_sensor_data = json.load(f)

        # センサと取得メソッドの対応
        self.sensors = {
            Sensor.TEMP    : self.sensor_manager.temperature,
            Sensor.HD      : self.sensor_manager.humidity,
            Sensor.I_LX    : self.sensor_manager.inner_lx,
            Sensor.U_LX    : self.sensor_manager.outer_lx,
            # Sensor.TEMPHQ  : self.sensor_manager.opt_temperature,
            # Sensor.HDHQ    : self.sensor_manager.opt_humidity,
            # Sensor.STEM    : self.sensor_manager.stem,
            # Sensor.FRUIT   : self.sensor_manager.fruit_diameter,
        }

    def get(self, sensor_name : str):
        """
        指定されたセンサのデータを取得するメソッド

        Args:
            sensor_name(str): センサ名

        Returns:
            result(SensorResult): センサデータの状態
            data(float): センサデータ
            retry_count(int): 成功までに要した再試行の回数（0始まり。全失敗時はmax_retry）
            is_fallback(bool): 取得に失敗し前回値で代替したか（True=代替値）

        Notes:
            指定された回数だけデータ取得を試み、
            正常に取得できない場合は前回の値を返す
        """
        result = SensorResult.EMPTY_STRING_ERROR
        max_retry = self.config['sensor']['max_retry_count'].get(sensor_name, 3)
        retry_count = 0

        for attempt in range(max_retry):
            retry_count = attempt
            try:
                # センサデータの取得
                data = float(self.sensors[sensor_name])
                # 取得後の待機時間
                time.sleep(self.config['sensor']['sleep_time'].get(sensor_name, 0.1))
                # データの妥当性検証
                result = self._is_valid(data, sensor_name)
                # データが正常な場合
                if result == SensorResult.SUCCESS:
                    # 前回のセンサデータを更新
                    with open(self.previous_data_path, 'w') as f:
                        self.previous_sensor_data[sensor_name] = data
                        json.dump(self.previous_sensor_data, f, indent=4)
                    return result, data, retry_count, False
            except Exception as e:
                print(f"センサ取得エラー ({sensor_name}): {e}")
            finally:
                # リトライ間隔
                time.sleep(self.config['sensor']['retry_interval'].get(sensor_name, 0.5))
        # すべてのリトライに失敗した場合、前回の値を返す
        return result, self.previous_sensor_data[sensor_name], max_retry, True

    def collect_with_status(self):
        """
        全センサの値と収集状態をまとめて取得するメソッド

        Returns:
            timestamp(str): 収集時刻（タイムゾーン付きISO8601）
            values(dict): センサ名 -> 値
            status(dict): センサ名 -> 収集状態
                {
                    "result":      状態名（SUCCESS / MAX_VALUE_ERROR など）,
                    "retry_count": 成功までの再試行回数,
                    "is_fallback": 前回値で代替したか（bool）
                }

        Notes:
            値だけでなく「その値が実測か代替値か」「何回リトライしたか」を
            収集時点で記録するためのメソッド。
            これらは後から復元できない情報のため、収集時に取得する。
        """
        values = {}
        status = {}
        for sensor_name in self.sensors.keys():
            result, data, retry_count, is_fallback = self.get(sensor_name)
            values[sensor_name] = data
            status[sensor_name] = {
                "result":      result.name,
                "retry_count": retry_count,
                "is_fallback": is_fallback,
            }
        timestamp = datetime.now(timezone.utc).astimezone().isoformat()
        return timestamp, values, status

    def upload_csv(self):
        """
        センサデータを取得し、InfluxDBにアップロードまたはCSVに保存するメソッド

        Returns:
            df(pd.DataFrame): アップロードしたデータ

        Notes:
            全センサのデータを取得
            データの取得に失敗した場合はCSVにデータを保存
        """
        # センサデータの取得（get()の戻り値のうち値[index 1]を使用）
        df = pd.DataFrame(
            data  = {sensor_name : self.get(sensor_name)[1] for sensor_name in self.sensors.keys()},
            # index = [datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')]
            index = [datetime.now(timezone.utc).astimezone().isoformat()]
        )

        # try:
        #     # InfluxDBにデータをアップロード
        #     InfluxDB().upload_dataframe(df)
        # except Exception as e:
        #     print(f"InfluxDBアップロードエラー: {e}")
        #finally:
        csv_path = Path(self.config['sensor']['csv_dir']) / f"{self.config['device_id']}_{self.config['aws_iot']['field_id']}_{self.config['aws_iot']['project_id']}_{datetime.now().strftime('%Y%m%d-%H%M.csv')}"
        df.to_csv(csv_path)

        return df

    def upload_csv_with_status(self):
        """
        センサデータと収集状態を取得し、値をCSVに保存するメソッド

        Returns:
            df(pd.DataFrame): 取得したセンサ値
            timestamp(str): 収集時刻
            values(dict): センサ名 -> 値
            status(dict): センサ名 -> 収集状態

        Notes:
            upload_csv() の拡張版。センサ取得を一度だけ行い、
            値のCSV保存と収集状態の取得を同時に行う。
            収集状態はMQTT送信などクラウド連携に用いる。
        """
        timestamp, values, status = self.collect_with_status()

        df = pd.DataFrame(data=values, index=[timestamp])

        csv_path = Path(self.config['sensor']['csv_dir']) / f"{self.config['device_id']}_{self.config['aws_iot']['field_id']}_{self.config['aws_iot']['project_id']}_{datetime.now().strftime('%Y%m%d-%H%M.csv')}"
        df.to_csv(csv_path)

        return df, timestamp, values, status

    def _is_valid(self, data, sensor:str):
        """
        センサデータの妥当性を検証するメソッド

        Args:
            data(int|float): センサデータ
            sensor(str): センサ名

        Returns:
            SensorResult: データの状態
        """
        # データが空の場合
        if not data:
            return SensorResult.EMPTY_STRING_ERROR
        # NaNの場合
        if data == 'nan':
            return SensorResult.NAN_ERROR
        # 無限大の場合
        if data == 'inf':
            return SensorResult.INF_ERROR
        # 最小値チェック
        min_value = self.config['sensor']['min_value'].get(sensor, float('-inf'))
        if float(data) < min_value:
            return SensorResult.MIN_VALUE_ERROR
        # 最大値チェック
        max_value = self.config['sensor']['max_value'].get(sensor, float('inf'))
        if float(data) > max_value:
            return SensorResult.MAX_VALUE_ERROR
        # すべてのチェックを通過
        return SensorResult.SUCCESS


if __name__ == "__main__":
    sensor = Sensor()
    # 収集状態も確認する
    df, timestamp, values, status = sensor.upload_csv_with_status()
    print(df)
    print("timestamp:", timestamp)
    print("status:")
    print(json.dumps(status, indent=2, ensure_ascii=False))