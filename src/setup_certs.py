"""
IoT証明書を使ってSecrets Managerから最新証明書を取得・更新する
初回は transfer_certs.sh で証明書を転送後に実行する
以降は起動時に自動実行（アクセスキー不要）

使い方:
    python3 setup_certs.py
"""
import boto3
import json
import os
import ssl
import urllib.request
import util

REGION     = 'ap-northeast-1'
CERT_DIR   = '/etc/iot'
ROLE_ALIAS = 'AgriDeviceSecretsAlias'


def get_temp_credentials(credentials_endpoint: str) -> dict:
    """
    IoT証明書でIoT Credentials Providerから一時IAMトークンを取得する

    Args:
        credentials_endpoint: iot:CredentialProvider エンドポイント
            （通常のiot:Data-ATSとは別のエンドポイント）

    Returns:
        {"accessKeyId": "...", "secretAccessKey": "...", "sessionToken": "..."}
    """
    url = f'https://{credentials_endpoint}/role-aliases/{ROLE_ALIAS}/credentials'

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.load_verify_locations(f'{CERT_DIR}/root-CA.pem')
    ctx.load_cert_chain(f'{CERT_DIR}/cert.pem', f'{CERT_DIR}/private.key')

    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, context=ctx) as res:
        data = json.loads(res.read())
    return data['credentials']


def setup_certs():
    """
    IoT証明書で一時トークンを取得し、
    Secrets Managerから最新の証明書を取得して配置する
    """
    config               = util.get_pinode_config()
    device_id            = config["device_id"]
    credentials_endpoint = config["aws_iot"]["credentials_endpoint"]

    os.makedirs(CERT_DIR, exist_ok=True)

    # 初回チェック: IoT証明書が存在しない場合は転送が必要
    if not os.path.exists(f'{CERT_DIR}/cert.pem'):
        print("エラー: IoT証明書が見つかりません")
        print("先に開発PCから証明書を転送してください:")
        print("  ./scripts/transfer_certs.sh <device-name> <PiNodeのIP>")
        return False

    print("IoT Credentials Provider から一時トークンを取得中...")
    try:
        creds = get_temp_credentials(credentials_endpoint)
        print("一時トークンの取得成功")
    except Exception as e:
        print(f"一時トークンの取得失敗: {e}")
        print("既存の証明書をそのまま使用します")
        return False

    # 一時トークンでSecrets Managerにアクセス
    secret_name = f"iot-cert/{device_id}"
    print(f"Secrets Manager から証明書を取得中: {secret_name}")

    client = boto3.client(
        'secretsmanager',
        region_name           = REGION,
        aws_access_key_id     = creds['accessKeyId'],
        aws_secret_access_key = creds['secretAccessKey'],
        aws_session_token     = creds['sessionToken'],
    )
    secret = client.get_secret_value(SecretId=secret_name)
    certs  = json.loads(secret['SecretString'])

    # 証明書と秘密鍵を更新
    with open(f'{CERT_DIR}/cert.pem', 'w') as f:
        f.write(certs['certificatePem'])
    with open(f'{CERT_DIR}/private.key', 'w') as f:
        f.write(certs['privateKey'])
    os.chmod(f'{CERT_DIR}/private.key', 0o600)

    # root-CA.pem が存在しない場合のみダウンロード
    if not os.path.exists(f'{CERT_DIR}/root-CA.pem'):
        print("Amazon Root CA をダウンロード中...")
        urllib.request.urlretrieve(
            'https://www.amazontrust.com/repository/AmazonRootCA1.pem',
            f'{CERT_DIR}/root-CA.pem'
        )

    print("証明書の更新が完了しました")
    return True


if __name__ == '__main__':
    setup_certs()