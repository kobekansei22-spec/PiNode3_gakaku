import cv2
import timeout_decorator
import subprocess
import time
from cobs import cobs
import crcmod
import serial
import datetime as dt
import numpy as np
from pathlib import Path
from usb import USB
import util
import os  # ★ ロックファイルのために os をインポート

# ★ カメラリソースのロックファイルパス (camera_fast.py と同じパス)
CAMERA_LOCK_FILE = "/tmp/camera.lock"

class Camera:
    """
    カメラ撮影を行うためのクラス
    """
    def __init__(self):
        self.config = util.get_pinode_config()

    def save_images(self):
        """
        デバイスに応じたカメラ撮影を行うメソッド.
        ★ ロックファイルを使用してリソースの衝突を回避する
        """
        
        # --- ロック処理 開始 ---
        if os.path.exists(CAMERA_LOCK_FILE):
            print(f"[{dt.datetime.now()}] カメラは他のプロセスで使用中です。スキップします。")
            return False # ロックが取得できなかった
        
        try:
            # ロックファイルを作成して「使用中」にする
            with open(CAMERA_LOCK_FILE, 'w') as f:
                f.write(str(os.getpid()))
            
            # --- 元々の save_images の処理 (日付入りファイル名) ---
            devices = USB().get()
            success_flag = False
            for port, type, name in devices:
                if type == 'SPRESENSE':
                    file_name = "image{:1}/{}_{:02}_HDR_{}.jpg".format(port, self.config['device_id'], port, dt.datetime.now().strftime('%Y%m%d-%H%M'))
                    if SPRESENSE(name).save(file_name):
                        success_flag = True
                elif type == 'USB Camera':
                    file_name = "image{:1}/{}_{:02}_RGB_{}.jpg".format(port, self.config['device_id'], port, dt.datetime.now().strftime('%Y%m%d-%H%M'))
                    if UsbCamera(name).save(file_name):
                        success_flag = True
            
            return success_flag

        except Exception as e:
            print(f"save_images 中にエラーが発生しました: {e}")
            return False # 失敗

        finally:
            # --- ロック処理 終了 ---
            if os.path.exists(CAMERA_LOCK_FILE):
                os.remove(CAMERA_LOCK_FILE)

class SPRESENSE:
    """
    SPRESENSEに関する設定値,メソッドをまとめたクラス
    """
    BAUD_RATE 	= 115200 	
    TYPE_INFO 	= 0
    TYPE_IMAGE 	= 1
    TYPE_FINISH = 2
    TYPE_ERROR 	= 3

    def __init__(self, port_num):
        self.port_num = port_num
        self.config = util.get_pinode_config()

    def save(self, file_name):
        """
        SPRESENSEから受け取ったバイナリ画像を保存する
        """
        local_file_path = str(Path(self.config['camera']['image_dir']) / Path(file_name))
        
        # ★ フォルダが存在しない場合に作成する
        os.makedirs(os.path.dirname(local_file_path), exist_ok=True)
        
        # ★ リトライは3回から1回に変更 (衝突回避のため)
        for i in range(3):
            try:
                # ★ タイムアウトを3秒から5秒に延長
                with serial.Serial(self.port_num, self.BAUD_RATE, timeout=5) as ser:
                    time.sleep(2) # ★ 接続待機を5秒から2秒に短縮
                    img = self._get_image_data(ser)
                    print(f"save image : {local_file_path}")
                    with open(local_file_path, "wb") as f:
                        f.write(img)
                return True
            except Exception as e:
                print(f"SPRESENSE save エラー: {e}")
                # ★ リトライ時はリブートしない (ロックが長引くため)
                # self._reboot() 
        
        print(f"[{self.port_num}] failed to get image")
        return False

    def _reboot(self):
        # (この関数は変更なし)
        subprocess.call("sudo sh -c \"echo -n \"1-1\" > /sys/bus/usb/drivers/usb/unbind\"", shell=True)
        time.sleep(1)
        subprocess.call("sudo sh -c \"echo -n \"1-1\" > /sys/bus/usb/drivers/usb/bind\"", shell=True)
        time.sleep(5)

    # ★★★ SPRESENSE 安定化対応 (ここから) ★★★
    def _get_packet(self, ser, timeout=10): # ★ デフォルトタイムアウトを10秒に
        """
        接続しているシリアルポートから1パケット分データの受信を行う
        (COBSエラー、CRCエラー対策を強化)
        """
        buf = bytearray()
        start = time.time()
        while True:
            val = ser.read()
            if val == b'\x00':
                if len(buf) == 0:
                    start = time.time() 
                    continue
                break
            elif time.time() - start > timeout:
                print(f"[{self.port_num}] _get_packet タイムアウト ({timeout}秒)")
                return False, self.TYPE_ERROR, None, None
            
            if val: 
                buf += val
            else: 
                print(f"[{self.port_num}] ser.read() タイムアウト")
                return False, self.TYPE_ERROR, None, None
        
        try:
            decoded = cobs.decode(buf)
        except cobs.DecodeError as e: 
            print(f"[{self.port_num}] COBSデコードエラー: {e}, buf={buf.hex()}")
            return False, self.TYPE_ERROR, None, None

        if len(decoded) < 6: 
            print(f"[{self.port_num}] 短すぎるパケット: {decoded.hex()}")
            return False, self.TYPE_ERROR, None, None
            
        crc8_func = crcmod.predefined.mkCrcFun('crc-8maxim')
        crc = crc8_func(decoded[0:-1])
        is_crc_valid = (crc == decoded[-1])
        if not is_crc_valid:
            print(f"[{self.port_num}] CRCエラー")

        packet_type = decoded[0]
        index = int(decoded[1]) * 1000 + int(decoded[2]) * 100 + int(decoded[3]) * 10 + int(decoded[4])
        payload = decoded[5:-1]
        
        return is_crc_valid, packet_type, index, payload

    def _send_request_image(self, ser):
        """
        画像の送信を要求する (このファイルでは 'S')
        """
        ser.write(str.encode('S\n')) # ★ (あなたのコード 'S' を尊重)

    def _send_complete_image(self, ser):
        ser.write(str.encode('E\n'))

    def _send_request_resend(self, ser, index):
        ser.write(str.encode(f'R{index}\n'))

    @timeout_decorator.timeout(50, use_signals=False)
    def _get_image_data(self, ser):
        """
        SPRESENSEから画像データを受け取る
        (安定化対応)
        """
        
        ser.flushInput() # ★ 送信前に受信バッファをクリア
        
        # 1. 送信要求
        self._send_request_image(ser)

        # 2. INFOパケット待ち (タイムアウト15秒)
        ret, code, index, data = self._get_packet(ser, timeout=15)
        if ret and (code == self.TYPE_INFO):
            max_index = index
            if max_index <= 0 or max_index > 5000: 
                 raise ValueError(f"[{self.port_num}] 不正なINFOパケット (max_index: {max_index})")
            buf = [None] * (max_index + 1)
        else:
            print(f"[{self.port_num}] DEBUG: INFOパケット受信失敗。ret={ret}, code={code}")
            raise ValueError(f"[{self.port_num}] INFOパケット受信できません")

        # 3. 画像データ受信
        for i in range(len(buf)):
            ret, code, index, data = self._get_packet(ser, timeout=5)
            if ret:
                if (code == self.TYPE_IMAGE) or (code == self.TYPE_FINISH):
                    if 0 <= index < len(buf): 
                        buf[index] = data
                    else:
                        print(f"[{self.port_num}] 不正なインデックス {index} を受信（無視）")
                else:
                     print(f"[{self.port_num}] 画像データ受信中に予期せぬコード {code} を受信")

        # 4. 再送要求（１回まで）
        missing_indices = [i for i, v in enumerate(buf) if v is None]
        if missing_indices:
            print(f"[{self.port_num}] データ欠損。再送要求: {len(missing_indices)} 個")
            for i in missing_indices:
                self._send_request_resend(ser, i)
                ret, code, index, data = self._get_packet(ser, timeout=5)
                if ret and (code == self.TYPE_IMAGE or code == self.TYPE_FINISH):
                    if i == index: 
                        buf[i] = data
                    else:
                         print(f"[{self.port_num}] 再送要求 {i} に対し {index} が返ってきた")
                         if 0 <= index < len(buf):
                             buf[index] = data 
        
        # 5. 終了送信
        self._send_complete_image(ser)
        
        # 6. 最終チェック
        if None in buf:
            missing_count = sum(1 for v in buf if v is None)
            print(f"[{self.port_num}] データが {missing_count} 個欠損しています。")
            raise ValueError(f"[{self.port_num}] 再送後もデータ欠損")

        jpg_data = bytearray(b''.join(buf))
        print(f"[{self.port_num}] 画像データ {len(jpg_data)} bytes 受信完了")
        return jpg_data
    # ★★★ SPRESENSE 安定化対応 (ここまで) ★★★


class UsbCamera:
    """
    USBカメラで撮影した写真保存のためのクラス
    """
    def __init__(self, device_name):
        self.config = util.get_pinode_config()
        self.device_name = device_name
    
    @timeout_decorator.timeout(20)
    def save(self, file_name):
        
        try:
            device_id = int(self.device_name)
        except ValueError:
            print(f"エラー: USBカメラのデバイス名 {self.device_name} が不正です。")
            return False

        cap = cv2.VideoCapture(device_id, cv2.CAP_V4L)
        
        if not cap.isOpened():
            print(f"エラー: USBカメラ {device_id} を開けません。")
            return False

        for _ in range(50):
            ret, frame = cap.read()
        
        if not ret:
            print(f"エラー: USBカメラ {device_id} からフレームを読み込めません。")
            cap.release()
            return False

        local_file_path = str(Path(self.config['camera']['image_dir']) / Path(file_name))
        
        os.makedirs(os.path.dirname(local_file_path), exist_ok=True)

        print(f"save image : {local_file_path}")
        cv2.imwrite(local_file_path, frame)
        cap.release() 
        return True


if __name__ == '__main__':
    devices = USB().get()
    print(devices)
    for i, (port, type, name) in enumerate(devices):
        print(port, type, name)
        tm = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        if type == 'SPRESENSE':
            SPRESENSE(name).save(f"test_{port}_{tm}.jpg")
        elif type == 'USB Camera':
            UsbCamera(name).save(f"test_{port}_{tm}.jpg")
        
