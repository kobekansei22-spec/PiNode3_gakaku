import requests
import json

class Notifier:
    def __init__(self):
        # 【重要】URLは再発行したものに書き換えてください
        self.teams_url = "https://defaulte0d7dc0046214fe090b1df7b1b40b3.51.environment.api.powerplatform.com:443/powerautomate/automations/direct/workflows/828ae53b9cf84cc4859f2efc26a20919/triggers/manual/paths/invoke?api-version=1&sp=%2Ftriggers%2Fmanual%2Frun&sv=1.0&sig=O-HmMsWUOmcCXf7JfXlVl-2tj65ojm9BJ20OL7tE21o"
        
        self.line_token = "ここにLINEトークン"
        self.line_user_id = "ここにLINEユーザーID"

    def send_teams(self, text, title="メロン監視システム", mention_email="danish.adira.hidayat.22@shizuoka.ac.jp"):
        """
        Teamsへ通知を送る（Power Automateのループ処理対応版）
        """
        if not self.teams_url:
            print("Teams URLが設定されていません")
            return

        headers = {'Content-Type': 'application/json'}
        
        # --- メンション処理 ---
        entities = []
        display_text = text # 基本のテキスト

        if mention_email:
            mention_name = mention_email # 表示名
            
            # 1. 本文の先頭にメンションタグを追加
            display_text = f"<at>{mention_name}</at> {text}"
            
            # 2. メンションの実体（Entity）を作成
            mention_entity = {
                "type": "mention",
                "text": f"<at>{mention_name}</at>",
                "mentioned": {
                    "id": mention_email,
                    "name": mention_name
                }
            }
            entities.append(mention_entity)

        # --- ペイロード作成 (attachments 配列構造に戻す) ---
        payload = {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "contentUrl": None,
                    "content": {
                        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                        "type": "AdaptiveCard",
                        "version": "1.4",
                        "body": [
                            {
                                "type": "TextBlock",
                                "text": title,
                                "weight": "Bolder",
                                "size": "Medium",
                                "color": "Accent"
                            },
                            {
                                "type": "TextBlock",
                                "text": display_text, # タグ付きテキスト
                                "wrap": True
                            }
                        ],
                        # メンション情報はここ（contentの中）に入れる
                        "msteams": {
                            "entities": entities
                        }
                    }
                }
            ]
        }
        
        try:
            # URLは必ず「再発行した正しいもの」を使ってください
            response = requests.post(self.teams_url, headers=headers, json=payload)
            if response.status_code == 202:
                print(f"Teams送信成功: {text}")
            else:
                print(f"Teams送信エラー(Status: {response.status_code}): {response.text}")
        except Exception as e:
            print(f"Teams通信エラー: {e}")