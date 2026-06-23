import paho.mqtt.client as mqtt
import time
import json
import sys
import os

msgs = []
def on_msg(c, u, m, p=None):
    payload = m.payload.decode()
    msgs.append((m.topic, payload))

def on_conn(c, u, f, r, p=None):
    c.subscribe('edge/#')

client = mqtt.Client()
client.on_connect = on_conn
client.on_message = on_msg
client.connect('192.168.117.161', 1883, 10)
client.loop_start()

for i in range(15):
    time.sleep(1)
    if len(msgs) >= 5:
        break

client.loop_stop()
client.disconnect()

result_file = sys.argv[1] if len(sys.argv) > 1 else "mqtt_direct_result.json"
with open(result_file, 'w', encoding='utf-8') as f:
    json.dump({"count": len(msgs), "messages": [{"topic": t, "data": p[:300]} for t, p in msgs[:10]]}, f, indent=2, ensure_ascii=False)
