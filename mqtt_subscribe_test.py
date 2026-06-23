import paho.mqtt.client as mqtt
import time
import json
import sys

msgs = []
def on_msg(c, u, m, p=None):
    payload = m.payload.decode() if hasattr(m, 'payload') else str(m)
    msgs.append((m.topic if hasattr(m, 'topic') else '?', payload))
    sys.stderr.write(f"[MQTT] {payload[:300]}\n")
    sys.stderr.flush()

def on_conn(c, u, flags, rc, p=None):
    sys.stderr.write(f"Connected rc={rc}\n")
    sys.stderr.flush()
    c.subscribe('edge/#')

client = mqtt.Client()
client.on_connect = on_conn
client.on_message = on_msg

try:
    client.connect('127.0.0.1', 1883, 10)
except Exception as e:
    sys.stderr.write(f"Connect failed: {e}\n")
    sys.exit(1)

client.loop_start()

# 等待 20 秒收集消息
for i in range(20):
    time.sleep(1)
    if len(msgs) >= 10:
        break

client.loop_stop()
client.disconnect()

result_file = sys.argv[1] if len(sys.argv) > 1 else "mqtt_result.json"
with open(result_file, 'w', encoding='utf-8') as f:
    json.dump({"count": len(msgs), "messages": [{"topic": t, "data": p[:500]} for t, p in msgs[:20]]}, f, indent=2, ensure_ascii=False)
