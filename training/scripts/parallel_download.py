"""
多线程分块下载脚本 — 绕过 DNS 污染 + SSL 兼容
用法: python parallel_download.py <URL> <输出路径> [线程数]
"""
import sys
import os
import time
import ssl
import socket
import threading
import http.client
import urllib.request

# ===== DNS 映射表 (绕过污染) =====
DNS_MAP = {
    "zenodo.org": "188.184.98.114",
}


class ForcedIPHTTPConnection(http.client.HTTPConnection):
    """HTTP 连接：强制使用指定 IP"""
    def connect(self):
        host = self.host
        ip = DNS_MAP.get(host, host)
        self.sock = socket.create_connection((ip, self.port), self.timeout)


class ForcedIPHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS 连接：强制使用指定 IP，但保持原始 hostname 做 SNI"""
    def connect(self):
        host = self.host
        ip = DNS_MAP.get(host, host)
        self.sock = socket.create_connection((ip, self.port), self.timeout)
        # SNI 使用原始 hostname, 但关闭 hostname 验证 (因为 IP 不匹配)
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        self.sock = ctx.wrap_socket(self.sock, server_hostname=host)


class ForcedIPHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(ForcedIPHTTPSConnection, req)


def get_file_size(url):
    req = urllib.request.Request(url, method="HEAD")
    req.add_header("User-Agent", "Mozilla/5.0")
    opener = urllib.request.build_opener(ForcedIPHandler())
    with opener.open(req, timeout=30) as resp:
        accept_ranges = resp.headers.get("Accept-Ranges", "none")
        size = int(resp.headers.get("Content-Length", 0))
        return size, accept_ranges == "bytes"


class ChunkDownloader(threading.Thread):
    def __init__(self, url, out_path, start, end, chunk_id, progress_dict):
        super().__init__(daemon=True)
        self.url = url
        self.out_path = out_path
        self.start = start
        self.end = end
        self.chunk_id = chunk_id
        self.progress = progress_dict
        self.downloaded = 0
        self.done = False

    def run(self):
        retries = 3
        for attempt in range(retries):
            try:
                req = urllib.request.Request(self.url)
                req.add_header("User-Agent", "Mozilla/5.0")
                req.add_header("Range", f"bytes={self.start}-{self.end - 1}")

                opener = urllib.request.build_opener(ForcedIPHandler())
                with opener.open(req, timeout=120) as resp:
                    with open(self.out_path, "r+b") as f:
                        f.seek(self.start)
                        while True:
                            chunk = resp.read(256 * 1024)
                            if not chunk:
                                break
                            f.write(chunk)
                            self.downloaded += len(chunk)
                            self.progress[self.chunk_id] = self.downloaded
                self.done = True
                return
            except Exception as e:
                if attempt < retries - 1:
                    time.sleep(2)
                else:
                    print(f"\n[分块 {self.chunk_id}] 失败: {e}")


def main():
    if len(sys.argv) < 3:
        print("用法: python parallel_download.py <URL> <输出路径> [线程数]")
        sys.exit(1)

    url = sys.argv[1]
    out_path = sys.argv[2]
    num_threads = int(sys.argv[3]) if len(sys.argv) > 3 else 8

    print(f"正在获取文件大小...")
    file_size, supports_range = get_file_size(url)
    print(f"文件大小: {file_size / (1024**3):.2f} GB")
    print(f"支持 Range: {supports_range}")

    if not supports_range or file_size == 0:
        print("不支持分块下载，使用单线程")
        num_threads = 1
        chunk_size = file_size
    else:
        chunk_size = file_size // num_threads

    # 预分配文件
    out_dir = os.path.dirname(out_path)
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)
    if not os.path.exists(out_path):
        with open(out_path, "wb") as f:
            f.truncate(file_size)

    progress = {}
    threads = []
    for i in range(num_threads):
        start = i * chunk_size
        end = file_size if i == num_threads - 1 else (i + 1) * chunk_size
        t = ChunkDownloader(url, out_path, start, end, i, progress)
        threads.append(t)
        progress[i] = 0

    print(f"启动 {num_threads} 个线程下载...")
    for t in threads:
        t.start()

    start_time = time.time()
    try:
        while True:
            time.sleep(3)
            total_dl = sum(progress.values())
            elapsed = max(time.time() - start_time, 0.1)
            speed = total_dl / elapsed
            pct = (total_dl / file_size * 100) if file_size > 0 else 0
            eta = (file_size - total_dl) / speed if speed > 0 else 0

            print(f"\r进度: {pct:.1f}% | "
                  f"{total_dl/(1024**2):.0f}/{file_size/(1024**2):.0f} MB | "
                  f"速度: {speed/(1024**2):.2f} MB/s | "
                  f"剩余: {eta/60:.0f}分  ",
                  end="", flush=True)

            if all(t.done for t in threads):
                break
    except KeyboardInterrupt:
        print("\n中断，进度已保留 (重跑可续传)")

    total_dl = sum(progress.values())
    elapsed = time.time() - start_time
    if total_dl >= file_size:
        print(f"\n✅ 完成! 耗时 {elapsed/60:.1f}分")
    else:
        print(f"\n⚠️ 未完全下载 ({total_dl/(1024**2):.0f}/{file_size/(1024**2):.0f} MB)")


if __name__ == "__main__":
    main()
