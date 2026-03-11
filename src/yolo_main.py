from ultralytics import YOLO
import cv2
from mortor_test import mortor
import time
from pathlib import Path
from send import Notifier
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
        
        self.Move = mortor()
        self.Move.change_mode(servo_id = 1, mode = 0)
        self.Move.enable_torque(servo_id = 1)
        self.Move.change_mode(servo_id = 2, mode = 0)
        self.Move.enable_torque(servo_id = 2)

    def yolo(self, image_path):
        """YOLOで物体検出を行うメソッド"""
        self.image = cv2.imread(image_path)
        if self.image is None:
            print(f"エラー: 画像が見つかりません -> {image_path}")
            return None

        # 推論実行 (リスト形式で結果が返る)
        results = self.detect.predict(self.image, conf=0.8, save=True, exist_ok=True,imgsz = 640)
        
        # --- 【修正】検出結果の確認ロジック ---
        # 1枚の画像だけ処理しているので results[0] を見る
        result = results[0]
        boxes = result.boxes

        # ボックスが空（何も検出されなかった）場合
        if len(boxes) == 0:
            print("果実が見つかりませんでした。(検出数: 0)")
            return None

        # 最も信頼度の高い1つ目のボックスを取得
        box = boxes[0]
        print(f"信頼度(Conf): {box.conf.item():.4f}") # item()で数値として取り出す

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
        # 画面中央に、検出された物体と同じサイズの枠を計算（目標位置）
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
        
        # ファイル保存などをここで行うならコメントアウトを外す
        # P = Path(image_path)
        # file_name = P.name
        # cv2.imwrite(f"output_{file_name}", self.image)

    def move_mortor(self, pan_diff, tilt_diff):
        """モーターを動かす（仮実装）"""
        # 変数名の重複を避けるため引数名を変更しました (new_pan -> pan_diff)
        
        now_pan = self.Move.read_servo(servo_id = 2)
        now_tilt = self.Move.read_servo(servo_id=1)
        target_pan = now_pan + pan_diff
        target_tilt = now_tilt + tilt_diff
        
        print(f"Motor Move -> Pan差分: {pan_diff}, Tilt差分: {tilt_diff}")
        self.Move.move_servo(position = int(target_pan), servo_id = 2)
        self.Move.move_servo(position = int(target_tilt), servo_id = 1)

    def cal_mortor(self, bbox):
        """現在位置と目標位置の差分からモーター指令値を計算"""
        # bboxは [x1, y1, x2, y2]
        # 比較すべきは「中心座標」どうしか、「左上の座標」どうし
        # ここでは左上座標 (bbox[0], bbox[1]) と目標 (self.new_bbox[0], [1]) を比較
        
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
            print("画角調整完了 (Center Aligned)")
            return True
        else:
            self.move_mortor(pan_diff, tilt_diff)
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
        
    def start(self, image_path):
        start_time = time.time()
        
        # 1. 画像サイズの取得
        self.get_image_size_cv2(image_path)
        
        # 2. YOLO推論とボックス取得
        bbox = self.yolo(image_path)
        
        # 検出されなかった場合 (None) は処理を中断
        if bbox is None:
            print("処理を終了します。")
            self.notifier.se:nd_teams("画角が外れています！！")
            return

        # 3. 距離（大きさ）の判定
        if self.is_initial_bbox_acceptable(bbox):
            print("距離OK!!")
        else:
            print("距離を離してください (Too Close)")
            self.notifier.send_teams("【警告】カメラの距離が近いです")

        # 4. 描画とモーター計算
        self.write_bbox(image_path)
        # self.cal_mortor(bbox) # モーターが有効ならコメントアウトを外す

        end_time = time.time()
        print("画角調整終了")
        print(f'Total time: {end_time - start_time:.4f} sec')

# --- 実行ブロック ---
if __name__ == "__main__":
    yolo_app = YOLO_main()
    # Windowsパスのエスケープ問題を避けるため、r"..." を使うか / を使う
    # テスト画像のパスを指定してください
    yolo_app.start("melon_picture.png")