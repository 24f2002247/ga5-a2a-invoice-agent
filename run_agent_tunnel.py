import subprocess
import time
import re
import sys
import os
import json
import requests

sys.stdout.reconfigure(line_buffering=True)
DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_PORT = int(os.environ.get("PORT", "8000"))
CLOUDFLARED_PATH = r"C:\Users\Jayraj\cloudflared.exe"


def start():
    print(f"Starting A2A Invoice Agent Server on port {SERVER_PORT}...")
    server_log_path = os.path.join(DIR, "server.log")
    server_log_file = open(server_log_path, "w", encoding="utf-8")
    server_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(SERVER_PORT)],
        cwd=DIR,
        stdout=server_log_file,
        stderr=subprocess.STDOUT,
        text=True
    )

    # Health check
    for _ in range(25):
        time.sleep(1)
        try:
            r = requests.get(f"http://127.0.0.1:{SERVER_PORT}/healthz", timeout=1)
            if r.status_code == 200:
                print(f"A2A Invoice Agent is UP on port {SERVER_PORT}!")
                break
        except Exception:
            pass
    else:
        print("Server failed to respond to health check.")
        server_proc.terminate()
        return

    cf_log_path = os.path.join(DIR, "cf_tunnel.log")
    if os.path.exists(cf_log_path):
        try:
            os.remove(cf_log_path)
        except Exception:
            pass

    cf_log_file = open(cf_log_path, "a", encoding="utf-8")
    print(f"Launching Cloudflare tunnel for port {SERVER_PORT}...")
    cf_proc = subprocess.Popen(
        [CLOUDFLARED_PATH, "tunnel", "--url", f"http://127.0.0.1:{SERVER_PORT}"],
        stdout=cf_log_file,
        stderr=subprocess.STDOUT,
        text=True
    )

    public_base_url = None
    for _ in range(35):
        time.sleep(1)
        if os.path.exists(cf_log_path):
            with open(cf_log_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
                matches = re.findall(r"https://[a-zA-Z0-9\-]+\.trycloudflare\.com", content)
                if matches:
                    public_base_url = matches[0]
                    print(f"Obtained Cloudflare Tunnel URL: {public_base_url}")
                    break

    if not public_base_url:
        print("Failed to obtain Cloudflare tunnel URL within timeout.")
        return

    # Verify public HTTPS endpoints
    print("\nVerifying live public HTTPS endpoints...")
    try:
        r_health = requests.get(f"{public_base_url}/healthz", timeout=10)
        print(f"GET {public_base_url}/healthz -> Status {r_health.status_code}")
    except Exception as e:
        print(f"Failed to reach {public_base_url}/healthz: {e}")

    try:
        r_card = requests.get(f"{public_base_url}/.well-known/agent-card.json", timeout=10)
        card_data = r_card.json()
        print(f"GET {public_base_url}/.well-known/agent-card.json -> Status {r_card.status_code}")
        print(f"Supported interface URL: {card_data.get('supportedInterfaces', [{}])[0].get('url')}")
    except Exception as e:
        print(f"Failed to read agent card: {e}")

    submitted_a2a_url = f"{public_base_url}/a2a"
    agent_card_url = f"{public_base_url}/.well-known/agent-card.json"

    urls = {
        "base_url": public_base_url,
        "submitted_a2a_url": submitted_a2a_url,
        "agent_card_url": agent_card_url,
        "healthz_url": f"{public_base_url}/healthz"
    }

    sub_file = os.path.join(DIR, "submission_urls.json")
    with open(sub_file, "w", encoding="utf-8") as f:
        json.dump(urls, f, indent=2)

    print("\n" + "=" * 60)
    print(f"SUBMITTED A2A BASE URL : {submitted_a2a_url}")
    print(f"AGENT CARD URL         : {agent_card_url}")
    print(f"HEALTH CHECK URL       : {public_base_url}/healthz")
    print("=" * 60 + "\n")

    try:
        while True:
            time.sleep(10)
    except KeyboardInterrupt:
        print("Shutting down...")
        server_proc.terminate()
        cf_proc.terminate()


if __name__ == "__main__":
    start()
