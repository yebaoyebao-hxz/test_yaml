import ssl
import websocket

paths = [
    "/ws",
    "/game/ws",
    "/game/douyin/ws",
    "/game/douyin",
    "/game",
    "/socket",
    "/gateway",
    "/connect",
    "/v1/ws",
    "/",
]

for path in paths:
    url = f"wss://zs-bjfyl-dy.danmu.hxzdm.com{path}"
    try:
        ws = websocket.create_connection(url, sslopt={"cert_reqs": ssl.CERT_NONE}, timeout=5)
        print(f"OK  {url}  ->  HTTP {ws.status}")
        ws.close()
    except Exception as e:
        err = str(e).split("\n")[0][:100]
        print(f"NO  {url}  ->  {err}")
