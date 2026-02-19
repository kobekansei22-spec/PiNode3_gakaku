import sys
import time
import os
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# ★ 物体検出スクリプトがあるフォルダのパスを追加
# (data_collector.py が /home/pinode3/PiNode3/src にある場合)
sys.path.append('/home/pinode3/PiNode3/src')

# ★ 物体検出スクリプトをインポート
# (注: yolo_main.py に YOLO_main というクラスが存在する必要があります)
try:
    from yolo_main import YOLO_main
except ImportError as e:
    print(f"エラー: 'yolo_main' のインポートに失敗しました。: {e}")
    sys.exit(1)

# 監視するベースフォルダ
BASE_PATH = "/home/pinode3/data/image"
FOLDERS_TO_WATCH = ["image2"]

# ★ 停止するまでの回数を設定
STOP_AFTER_COUNT = 3

# ★ detector のインスタンス化 (YOLO_main クラスと仮定)
try:
    detector = YOLO_main()
except Exception as e:
    print(f"エラー: YOLO_main() のインスタンス化に失敗しました: {e}")
    sys.exit(1)


class FileCreatedHandler(FileSystemEventHandler):
    """
    ファイルが作成されたイベントを処理するクラス
    (カウント機能付き)
    """
    def __init__(self, observer_to_stop):
        self.file_count = 0 # ★ ファイルカウント用
        self.observer = observer_to_stop # ★ 停止させるObserverオブジェクト
        print(f"監視を開始します。{STOP_AFTER_COUNT} 個のファイルが作成されたら停止します。")

    def on_created(self, event):
        if event.is_directory:
            return

        self.file_count += 1 # ★ カウントを増やす
        new_file_path = event.src_path
        print(f"ファイルが追加されました: {new_file_path} ({self.file_count} / {STOP_AFTER_COUNT})")

        try:
            # ★ インポートした関数を直接呼び出す！
            detector.start(new_file_path)
            
        except Exception as e:
            print(f"物体検出の呼び出し中にエラー: {e}")

        # ★ カウントが上限に達したら
        if self.file_count >= STOP_AFTER_COUNT:
            print(f"{STOP_AFTER_COUNT} 個のファイルを処理しました。監視を停止します。")
            self.observer.stop() # ★ 監視を停止する


if __name__ == "__main__":
    # ★ オブザーバーを先に作成
    observer = Observer()
    # ★ ハンドラにオブザーバーを渡してインスタンス化
    event_handler = FileCreatedHandler(observer_to_stop=observer)
    
    for folder in FOLDERS_TO_WATCH:
        path_to_watch = os.path.join(BASE_PATH, folder)
        if not os.path.isdir(path_to_watch):
            print(f"警告: 監視対象フォルダが存在しません: {path_to_watch}")
            continue
        
        observer.schedule(event_handler, path_to_watch, recursive=False)
        print(f"{path_to_watch} の監視を開始します...")

    # 監視を開始
    observer.start()
    
    try:
        # ★ observer.stop() が呼ばれるまで、ここで待機する
        observer.join()
    except KeyboardInterrupt:
        print("ユーザーにより中断されました。")
        observer.stop()
    
    # join() が完了（＝監視が停止）したら、プログラムを終了
    print("監視プログラムを終了します。")
