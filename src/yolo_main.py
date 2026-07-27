from ultralytics import YOLO
import cv2
from mortor_test import mortor
import time
from pathlib import Path
from send import Notifier
import os
import sys # exit()のために必要

class YOLO_main():
    def __init__(self):
        # モデルのロード
        self.detect = YOLO("best_melon.pt") 
        # デフォルト値
        self.image_height, self.image_width = 960, 1280
        self.new_bbox = [0, 0, 0, 0] # 目標位置（画面中央）用
        self.bbox = [0, 0, 0, 0]     # 検出されたバウンディングボックス用
        self.notifier = Notifier()

        try:
            from usb import USB
        except ImportError:
            print("エラー: 'usb.py' が見つかりません。")
            print("このスクリプトと同じディレクトリに配置してください。")
            sys.exit(1)
        
        motor_ports = {
            "image1": "/dev/ttyUSB_2",
            "image2": "/dev/ttyUSB_1",
            "image3": "/dev/ttyUSB_4",
            "image4": "/dev/ttyUSB_3"
        }

        self.camera_setup = {}

        # 1. 接続されている全USBデバイスの情報を取得
        try:
            devices = USB().get()
            # 2. typeが 'mortor driver' と判定されたポート名（name）だけのリストを作成
            valid_motor_names = [name for port, dev_type, name in devices if dev_type == 'mortor driver']
        except Exception as e:
            print(f"警告: USB情報の取得に失敗しました: {e}")
            valid_motor_names = []

        for cam_id, port_path in motor_ports.items():
            # 3. ポートが物理的に存在し、かつ「モータドライバ」リストに含まれているかチェック
            if os.path.exists(port_path) and (port_path in valid_motor_names):
                try:
                    driver = mortor(port_name=port_path)
                    
                    # トルクON設定
                    driver.change_mode(servo_id=1, mode=0)
                    driver.enable_torque(servo_id=1)
                    driver.change_mode(servo_id=2, mode=0)
                    driver.enable_torque(servo_id=2)

                    self.camera_setup[cam_id] = {"driver": driver, "tilt": 1, "pan": 2}
                    print(f"[{cam_id}] モータドライバ接続成功: {port_path}")
                    
                except Exception as e:
                    print(f"[{cam_id}] ドライバ初期化エラー: {e}")
                    self.camera_setup[cam_id] = {"driver": None, "tilt": 1, "pan": 2}
                    
            else:
                # 誤認または未接続の場合のスキップ処理
                if not os.path.exists(port_path):
                    print(f"[{cam_id}] ポート未接続 ({port_path})")
                else:
                    print(f"[{cam_id}] 誤認を防止: {port_path} はモータドライバではありません")
                
                self.camera_setup[cam_id] = {"driver": None, "tilt": 1, "pan": 2}

    def yolo(self, image_path):
        """YOLOで物体検出を行うメソッド"""
        self.image = cv2.imread(image_path)
        if self.image is None:
            print(f"エラー: 画像が見つかりません -> {image_path}")
            return None

        # 推論実行 (リスト形式で結果が返る)
        results = self.detect.predict(self.image, conf=0.8, save=True, exist_ok=True, imgsz=640)
        
        result = results[0]
        boxes = result.boxes

        # ボックスが空（何も検出されなかった）場合
        if len(boxes) == 0:
            print("果実が見つかりませんでした。(検出数: 0)")
            return None

        # 最も信頼度の高い1つ目のボックスを取得
        box = boxes[0]
        print(f"信頼度(Conf): {box.conf.item():.4f}") 

        # 座標取得 [x1, y1, x2, y2]
        xyxy = box.xyxy[0].tolist()
        self.bbox = xyxy # クラス変数に保存

        # 幅と高さを計算
        self.width = xyxy[2] - xyxy[0]
        self.height = xyxy[3] - xyxy[1]

        return xyxy

    def get_image_size_cv2(self, image_path):
        """OpenCVを使用して画像サイズ (幅, 高さ) を取得する"""
        img = cv2.imread(image_path)
        if img is None:
            print("エラー: 画像を読み込めませんでした。")
            return
        
        self.image_height, self.image_width, _ = img.shape
        print(f"画像サイズ取得: {self.image_width}x{self.image_height}")

    def write_bbox(self, image_path):
        """目標となる中央の枠を描画する"""
        self.new_bbox[0] = (self.image_width - self.width) / 2
        self.new_bbox[2] = (self.image_width + self.width) / 2
        self.new_bbox[1] = (self.image_height - self.height) / 2
        self.new_bbox[3] = (self.image_height + self.height) / 2
        
        print(f"目標BBox: {self.new_bbox}")
        
        # 水色の枠を描画 (Target)
        cv2.rectangle(
            self.image, 
            (int(self.new_bbox[0]), int(self.new_bbox[1])), 
            (int(self.new_bbox[2]), int(self.new_bbox[3])), 
            color=(255, 255, 0), thickness=5
        )

    def move_mortor(self, pan_diff, tilt_diff, camera_id="image2"):
        # ★ 呼び出されたカメラに応じたドライバとIDを取得
        setup = self.camera_setup.get(camera_id)
        if setup is None or setup["driver"] is None:
            print(f"[{camera_id}] モータ未接続のため動作をスキップします")
            return
        driver = setup["driver"]
        pan_id = setup["pan"]
        tilt_id = setup["tilt"]

        now_pan = driver.read_servo(servo_id=pan_id)
        now_tilt = driver.read_servo(servo_id=tilt_id)
        
        target_pan = now_pan + pan_diff
        target_tilt = now_tilt + tilt_diff
        
        print(f"[{camera_id}] Motor Move -> Pan差分: {pan_diff}, Tilt差分: {tilt_diff}")
        
        # ★ 取り出した専用のドライバを経由してモータを動かす
        driver.move_servo(position=int(target_pan), servo_id=pan_id)
        driver.move_servo(position=int(target_tilt), servo_id=tilt_id)

    def cal_mortor(self, bbox, camera_id="image2"):
        """現在位置と目標位置の差分からモーター指令値を計算"""
        pan_flag, tilt_flag = 0, 0
        row_pan = bbox[0] - self.new_bbox[0]
        row_tilt = bbox[1] - self.new_bbox[1]
        
        # 閾値 25px
        if abs(row_pan) > 25:
            pan_diff = row_pan * 0.039 * 11.37
        else:
            pan_diff = 0
            pan_flag = 1
            
        if abs(row_tilt) > 25:
            tilt_diff = row_tilt * 0.039 * 11.37
        else:
            tilt_diff = 0
            tilt_flag = 1
            
        if pan_flag == 1 and tilt_flag == 1:
            print(f"[{camera_id}] 画角調整完了 (Center Aligned)")
            return True
        else:
            # ★ 計算した差分とcamera_idを渡す
            self.move_mortor(pan_diff, tilt_diff, camera_id)
            return False

    def is_initial_bbox_acceptable(self, bbox_coords: tuple, growth_factor: float = 2) -> bool:
        """距離（画角占有率）の判定"""
        x_min, y_min, x_max, y_max = bbox_coords
        bbox_width = x_max - x_min
        bbox_height = y_max - y_min
        
        max_linear_ratio = 1.0 / growth_factor
        width_ratio = bbox_width / self.image_width
        height_ratio = bbox_height / self.image_height
        
        is_width_acceptable = width_ratio <= max_linear_ratio
        is_height_acceptable = height_ratio <= max_linear_ratio
        
        print(f"判定: 幅率={width_ratio:.2f}, 高さ率={height_ratio:.2f} (許容ライン: {max_linear_ratio:.2f})")
        return is_width_acceptable and is_height_acceptable
        
    def start(self, image_path, camera_id="image2"):
        """監視スクリプトから呼び出されるエントリーポイント"""
        start_time = time.time()
        print(f"--- [{camera_id}] の処理を開始 ---")
        
        # 1. 画像サイズの取得
        self.get_image_size_cv2(image_path)
        
        # 2. YOLO推論とボックス取得
        bbox = self.yolo(image_path)
        
        # 検出されなかった場合 (None) は処理を中断
        if bbox is None:
            print("処理を終了します。")
            # ★ 【修正】 se:nd_teams というタイポを send_teams に修正
            #self.notifier.send_teams(f"[{camera_id}] 画角が外れています！！")
            return

        # 3. 距離（大きさ）の判定
        if self.is_initial_bbox_acceptable(bbox):
            print("距離OK!!")
        else:
            print("距離を離してください (Too Close)")
            #self.notifier.send_teams(f"【警告】[{camera_id}] カメラの距離が近いです")

        # 4. 描画とモーター計算
        self.write_bbox(image_path)
        
        # ★ camera_id を cal_mortor に引き継ぐ
        self.cal_mortor(bbox, camera_id) 

        end_time = time.time()
        print(f"[{camera_id}] 画角調整終了")
        print(f'Total time: {end_time - start_time:.4f} sec')

# --- 実行ブロック ---
if __name__ == "__main__":
    yolo_app = YOLO_main()
    # 単体テスト用
    yolo_app.start("/home/pinode3/data/image/image3/00_03_RGB_20260601-1813.jpg", camera_id="image3")