import serial
import time
import sys
import tty
import termios
from camera_fast import Camera


try:
    from usb import USB
except ImportError:
    print("エラー: 'usb.py' が見つかりません。")
    print("このスクリプトと同じディレクトリに配置してください。")
    sys.exit(1)


#モータ制御の各関数が格納されたクラス
#main関数呼び出しで手動操作可能
class mortor:
    """
    サーボモーターを制御するクラス
    """
    def __init__(self, baudrate=1000000):
        """
        初期化時に 'MOTOR DRIVER' を探し、シリアルポートを開く
        """
        self.port = None
        self.ser = None
        devices = USB().get()
        
        for port, type, name in devices:
            if type == 'mortor driver': 
                # self.port = f'/dev/ttyUSB_{port}'
                self.port = name 
                break

        if self.port is None:
            raise RuntimeError("MOTOR DRIVER が見つかりません。USB接続を確認してください。")

        try:
            # シリアルポートを一度だけ開く
            self.ser = serial.Serial(self.port, baudrate, timeout=0.1)
            print(f"モータードライバに接続しました: {self.port}")
        except serial.SerialException as e:
            print(f"エラー: {self.port} を開けません: {e}")
            sys.exit(1)

    def close(self):
        """
        シリアルポートを閉じる
        """
        if self.ser and self.ser.is_open:
            self.ser.close()
            print("\nシリアルポートを閉じました。")

    def _send_packet(self, packet):
        """
        パケットを送信する内部ヘルパー関数
        """
        if not self.ser or not self.ser.is_open:
            print("エラー: シリアルポートが開いていません。")
            return
            
        # チェックサム計算：~(IDから最後のパラメータまでの合計) & 0xFF
        checksum = (~sum(packet[2:])) & 0xFF
        packet.append(checksum)
        
        # デバッグ用に送信パケットを表示
        # print(f"送信: {list(packet)}")
        
        # 送信
        self.ser.write(bytearray(packet))
        
        # 短い待機（モーターが応答を返すための時間）
        time.sleep(0.001) 

    def enable_torque(self, servo_id=1, enable=1):
        """
        サーボのトルクをON(1)またはOFF(0)にする
        """
        # Torque Enable のアドレスは 0x28
        packet = [0xFF, 0xFF, servo_id, 4, 0x03, 0x28, enable]
        self._send_packet(packet)

    def move_servo(self, servo_id=1, position=2048):
        """
        指定したIDのサーボを特定の位置（角度）に移動させる
        """
        # 位置を 2バイトに分解
        pos_l = position & 0xFF
        pos_h = (position >> 8) & 0xFF

        # Goal Position のアドレスは 0x2A
        packet = [0xFF, 0xFF, servo_id, 5, 0x03, 0x2A, pos_l, pos_h]
        self._send_packet(packet)

    def read_servo(self, servo_id=1):
        """
        指定したIDのサーボから現在の位置を読み取る
        """
        # Present Position のアドレス 0x38 から 2 バイト読み出し
        packet = [0xFF, 0xFF, servo_id, 4, 0x02, 0x38, 2]
        
        self.ser.flushInput() # 受信バッファをクリア
        self._send_packet(packet)
        
        # 応答を待つ
        time.sleep(0.01) # 読み取りには少し長めの待機
        
        if self.ser.in_waiting:
            response = self.ser.read(self.ser.in_waiting)
            # 応答パケットの最小長とヘッダを検証
            if len(response) >= 8 and response[0] == 0xFF and response[1] == 0xFF:
                pos_l = response[5]
                pos_h = response[6]
                position = pos_l + (pos_h << 8)
                return position
        return None

    def move_speed(self, servo_id=1, speed=1024):
        """
        指定したIDのサーボの最高速度を設定 (位置制御モード用)
        """
        # 位置を 2バイトに分解
        pos_l = speed & 0xFF
        pos_h = (speed >> 8) & 0xFF

        # Goal Speed のアドレスは 0x2E
        packet = [0xFF, 0xFF, servo_id, 5, 0x03, 0x2E, pos_l, pos_h]
        self._send_packet(packet)

    def speed_focus(self, servo_id=3, speed = 1000, dir = 0):
        """
        指定したIDのサーボを速度制御モードで回転させる
        dir=0: CCW (反時計回り), dir=1: CW (時計回り)
        """
        # 速度と方向を結合 (dir=1 の場合、15ビット目を立てる)
        send = speed + (dir * 32768)
        pos_l = send & 0xFF
        pos_h = (send >> 8) & 0xFF

        # Goal Speed のアドレスは 0x2E
        packet = [0xFF, 0xFF, servo_id, 5, 0x03, 0x2E, pos_l, pos_h]
        self._send_packet(packet)

    def stop_focus(self, servo_id=3, speed = 0):
        """
        指定したIDのサーボの回転を停止させる (速度を0にする)
        """
        pos_l = speed & 0xFF
        pos_h = (speed >> 8) & 0xFF

        # Goal Speed のアドレスは 0x2E
        packet = [0xFF, 0xFF, servo_id, 5, 0x03, 0x2E, pos_l, pos_h]
        self._send_packet(packet)

    def change_mode(self, servo_id=3, mode=0, torque_on=True):
        """
        サーボの動作モードを変更する
        mode=0: 位置制御モード (角度指定)
        mode=1: G速度制御モード (回転し続ける)
        
        STSサーボはモード変更時にトルクがOFFになるため、
        torque_on=True の場合、モード変更後に即座にトルクをONに戻す。
        """
        # 1. Mode のアドレス 0x21 に書き込み
        packet = [0xFF, 0xFF, servo_id, 4, 0x03, 0x21, mode]
        self._send_packet(packet)
        
        # 2. モード変更直後にトルクをON (1) にする (アドレス 0x28)
        if torque_on:
            self.enable_torque(servo_id, 1)

# --- キー入力のための関数 ---
def getch():
    """
    Enterキー不要で1文字のキー入力を受け取る (Linux/Mac用)
    """
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    return ch

# --- メインの実行部分 ---
if __name__ == '__main__':
    
    try:
        move = mortor()
    except Exception as e:
        print(f"初期化エラー: {e}")
        sys.exit(1)

    # 全てのサーボ(1, 2, 3)を速度制御モード(mode=1)に変更
    print("サーボ 1, 2, 3 を速度制御モードに設定します...")
    move.change_mode(servo_id=1, mode=1)
    move.change_mode(servo_id=2, mode=1)
    move.change_mode(servo_id=3, mode=1)
    time.sleep(0.1) # モード変更のための待機

    print("\n--- キーボード制御開始 ---")
    print("w/s : チルト (サーボ2)")
    print("a/d : パン (サーボ1)")
    print("r/f : フォーカス (サーボ3)")
    print("c   : 画像キャプチャ(サムネイル)")
    print("スペース: 全停止")
    print("q : 終了")
    print("-------------------------")

    # 速度 (0-1023)
    MOVE_SPEED = 1000
    FOCUS_SPEED = 500

    # ターミナルの設定を保持
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)

    try:
        tty.setcbreak(sys.stdin.fileno())

        while True:
            key = sys.stdin.read(1) # 1文字読み取り

            if key == 'q':
                print("終了します...")
                break
            
            # --- パン (サーボ1) ---
            elif key == 's':
                print("チルト 下 (S1, Dir 0)")
                move.speed_focus(servo_id=1, speed=MOVE_SPEED, dir=0)
                time.sleep(0.01)
                move.stop_focus(servo_id=1)
            elif key == 'w':
                print("チルト 上 (S1, Dir 1)")
                move.speed_focus(servo_id=1, speed=MOVE_SPEED, dir=1)
                time.sleep(0.01)
                move.stop_focus(servo_id=1)
            
            # --- チルト (サーボ2) ---
            elif key == 'd':
                print("パン 右 (S2, Dir 0)")
                move.speed_focus(servo_id=2, speed=MOVE_SPEED, dir=0)
                time.sleep(0.01)
                move.stop_focus(servo_id=2)
            elif key == 'a':
                print("パン 左 (S2, Dir 1)")
                move.speed_focus(servo_id=2, speed=MOVE_SPEED, dir=1)
                time.sleep(0.01)
                move.stop_focus(servo_id=2)

            # --- フォーカス (サーボ3) ---
            elif key == 'r':
                print("フォーカス + (S3, Dir 0)")
                move.speed_focus(servo_id=3, speed=FOCUS_SPEED, dir=0)
            elif key == 'f':
                print("フォーカス - (S3, Dir 1)")
                move.speed_focus(servo_id=3, speed=FOCUS_SPEED, dir=1)

            # --- 停止 ---
            elif key == ' ':
                print("全停止")
                move.stop_focus(servo_id=1)
                move.stop_focus(servo_id=2)
                move.stop_focus(servo_id=3)

            elif key == 'c':
                print("画像")
                Camera().save_images()
            
            # (オプション) 現在位置の読み取り
            # elif key == 'p':
            #     pos1 = move.read_servo(servo_id=1)
            #     pos2 = move.read_servo(servo_id=2)
            #     print(f"現在位置 S1: {pos1}, S2: {pos2}")

    except KeyboardInterrupt:
        print("\nCtrl+C で中断されました。")
    
    finally:
        # --- 終了処理 ---
        # ターミナルの設定を元に戻す
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        
        # 全てのモーターを停止
        print("全モーターを停止します...")
        move.stop_focus(servo_id=1)
        move.stop_focus(servo_id=2)
        move.stop_focus(servo_id=3)
        
        # シリアルポートを閉じる
        move.close()
