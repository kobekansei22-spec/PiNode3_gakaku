def is_initial_bbox_acceptable(bbox_coords: tuple, image_size: tuple, growth_factor: float = 3.0) -> bool:
    """
    果実が最終的に画角に収まるかどうかの判定を行う関数。

    Args:
        bbox_coords (tuple): 検出されたBBoxの座標 (x_min, y_min, x_max, y_max)
        image_size (tuple): 画像全体のサイズ (width, height)
        growth_factor (float): 最終的な果実の拡大率 (デフォルト: 3.0)

    Returns:
        bool: BBoxが許容範囲内であれば True、超えていれば False
    """
    # 1. 画像とBBoxのサイズを取得
    img_width, img_height = image_size
    x_min, y_min, x_max, y_max = bbox_coords
    
    bbox_width = x_max - x_min
    bbox_height = y_max - y_min
    
    # 2. 最大許容線形割合 (辺の長さの割合) を計算
    # 拡大率 S が 3.0 の場合、最大許容線形割合は 1 / 3.0 ≈ 0.3333
    max_linear_ratio = 1.0 / growth_factor
    
    # 3. 現在のBBoxの辺の長さが画像全体に占める割合を計算
    width_ratio = bbox_width / img_width
    height_ratio = bbox_height / img_height
    
    # 4. 判定ロジック
    # 最終的に画角に収まるためには、幅と高さの両方が許容割合を超えてはならない
    is_width_acceptable = width_ratio <= max_linear_ratio
    is_height_acceptable = height_ratio <= max_linear_ratio
    
    # --- 判定詳細の出力 (デバッグ/ログ用) ---
    print("--- 判定詳細 (拡大率 2.0倍) ---")
    print(f"許容される最大線形割合: {max_linear_ratio:.4f} ({max_linear_ratio * 100:.2f}%)")
    print(f"現在の幅の割合: {width_ratio:.4f} ({width_ratio * 100:.2f}%) -> 許容: {is_width_acceptable}")
    print(f"現在の高さの割合: {height_ratio:.4f} ({height_ratio * 100:.2f}%) -> 許容: {is_height_acceptable}")
    print(f"現在の面積の割合: {(width_ratio * height_ratio) * 100:.2f}%")
    
    # 総合判定: 両方の辺が許容範囲内であること
    return is_width_acceptable and is_height_acceptable

# --- 実行例 ---

# 設定 (拡大率 2.0倍)
GROWTH_FACTOR = 2.0
IMAGE_SIZE = (1920, 1080) # 画像の幅, 高さ (ピクセル)
MAX_RATIO = 1 / 2 # 約 0.3333

# ----------------------------------------------------
# 例 1: 許容範囲内 (幅: 30%, 高さ: 27.8%)
# 最終的に 30% * 3 = 90%, 27.8% * 3 = 83.3% で収まる
bbox_ok = (50, 50, 626, 350)  # 幅: 576px (1920*0.3), 高さ: 300px (1080*0.278)
print("\n[例 1: 許容範囲内 BBox]")
result_ok = is_initial_bbox_acceptable(bbox_ok, IMAGE_SIZE, GROWTH_FACTOR)
print(f"総合判定: {'OK' if result_ok else 'NG'}\n")


# ----------------------------------------------------
# 例 2: 許容範囲オーバー (幅が 33.3% を超過)
# 幅: 700px / 1920px ≈ 36.46% (NG)
bbox_ng = (50, 50, 750, 350) 
print("[例 2: 許容範囲オーバー BBox]")
result_ng = is_initial_bbox_acceptable(bbox_ng, IMAGE_SIZE, GROWTH_FACTOR)
print(f"総合判定: {'OK' if result_ng else 'NG'}")