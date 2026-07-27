import sys
import time
import os
import threading # ★ 同時実行を防ぐためのモジュールを追加
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

sys.path.append('/home/pinode3/PiNode3/src')
try:
    from yolo_main import YOLO_main
except ImportError as e:
    print(f"エラー: 'yolo_main' のインポートに失敗しました。: {e}")
    sys.exit(1)

try:
    from usb import USB
except ImportError:
    print("エラー: 'usb.py' が見つかりません。")
    print("このスクリプトと同じディレクトリに配置してください。")
    sys.exit(1)

FOLDERS_TO_WATCH = []

devices = USB().get()
for port, type, name in devices:
    if type == 'SPRESENSE' or type == 'USB Camera': 
        FOLDERS_TO_WATCH.append(f"image{port}") 

BASE_PATH = "/home/pinode3/data/image"
# ★ 監視するフォルダを2つに拡張


STOP_AFTER_COUNT = 4

try:
    detector = YOLO_main()
except Exception as e:
    print(f"エラー: YOLO_main() のインスタンス化に失敗しました: {e}")
    sys.exit(1)

# ★ YOLO処理が同時に走らないようにするためのロック
yolo_lock = threading.Lock()


class FileCreatedHandler(FileSystemEventHandler):
    def __init__(self, observer_to_stop):
        self.file_count = 0
        self.observer = observer_to_stop
        print(f"監視を開始します。合計 {STOP_AFTER_COUNT} 個のファイルが作成されたら停止します。")

    def on_created(self, event):
        if event.is_directory:
            return

        self.file_count += 1
        new_file_path = event.src_path
        
        # ★ パスからフォルダ名（image2 や image4）を取得し、カメラを識別
        camera_id = os.path.basename(os.path.dirname(new_file_path))
        
        print(f"[{camera_id}] ファイルが追加されました: {new_file_path} ({self.file_count} / {STOP_AFTER_COUNT})")
        time.sleep(0.5)

        # ★ ロックを取得してからYOLOを実行（他が処理中の場合は待機する）
        with yolo_lock:
            try:
                # ★ どちらのカメラの画像かを detector に伝える
                # ※ YOLO_main クラス側の start メソッドが第2引数を受け取れるよう修正が必要です
                detector.start(new_file_path, camera_id)
            except Exception as e:
                print(f"物体検出の呼び出し中にエラー: {e}")

        if self.file_count >= STOP_AFTER_COUNT:
            print(f"合計 {STOP_AFTER_COUNT} 個のファイルを処理しました。監視を停止します。")
            self.observer.stop()


if __name__ == "__main__":
    observer = Observer()
    
    # ★ ハンドラ（監視員）は1つだけ作成し、カウントを全体で共有する
    event_handler = FileCreatedHandler(observer_to_stop=observer)
    
    for folder in FOLDERS_TO_WATCH:
        path_to_watch = os.path.join(BASE_PATH, folder)
        
        # フォルダが存在しない場合は作成（あるいは警告）
        if not os.path.isdir(path_to_watch):
            print(f"警告: 監視対象フォルダが存在しません。作成します: {path_to_watch}")
            os.makedirs(path_to_watch, exist_ok=True)
        
        # ★ 同じハンドラを使って、両方のフォルダを監視リストに登録
        observer.schedule(event_handler, path_to_watch, recursive=False)
        print(f"{path_to_watch} の監視を開始します...")

    observer.start()
    
    try:
        observer.join()
    except KeyboardInterrupt:
        print("ユーザーにより中断されました。")
        observer.stop()
    
    print("監視プログラムを終了します。")