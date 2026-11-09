import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "validation"))
from hermes_transport_client import HermesTransportClient

configuration = json.load(sys.stdin)
client = HermesTransportClient(configuration["endpoint"], configuration["capability"], configuration["run_id"])
try:
    first = client.prepare_turn()
    second = client.prepare_turn()
    if first != second:
        raise ValueError("重复读取的补充输入不一致")
    print(json.dumps(first, ensure_ascii=False))
finally:
    client.close()
