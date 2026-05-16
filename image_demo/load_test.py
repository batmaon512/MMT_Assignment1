import urllib.request
import json
import base64
import time
import os
import concurrent.futures

import argparse

# Configuration
SERVER_URL = "http://127.0.0.1:8080/images/process"
IMAGE_PATH = os.path.join("test_image", "demo1.jpg")

def send_request(req_id, base64_image):
    payload = {"image": base64_image}
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(SERVER_URL, data=data, headers={'Content-Type': 'application/json'}, method='POST')
    
    start_time = time.time()
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            status = response.getcode()
            res_data = json.loads(response.read().decode('utf-8'))
            elapsed = time.time() - start_time
            if status == 200 and 'image' in res_data:
                print(f"[Req {req_id:03d}] Success ({elapsed:.2f}s)")
                return True
            else:
                error_msg = res_data.get('error', 'Unknown Error')
                print(f"[Req {req_id:03d}] Failed: {status} - {error_msg} ({elapsed:.2f}s)")
                return False
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"[Req {req_id:03d}] Exception: {e} ({elapsed:.2f}s)")
        return False

def main():
    parser = argparse.ArgumentParser(description="Load Test cho AsynApRous")
    parser.add_argument("-t", "--total", type=int, default=50, help="Tổng số request (mặc định: 50)")
    parser.add_argument("-c", "--concurrent", type=int, default=10, help="Số worker đồng thời (mặc định: 10)")
    args = parser.parse_args()
    
    total_reqs = args.total
    concurrent_reqs = args.concurrent

    if not os.path.exists(IMAGE_PATH):
        print(f"Error: Image not found at {IMAGE_PATH}")
        fallback_path = "demo1.jpg"
        if os.path.exists(fallback_path):
            print(f"Found image at {fallback_path} instead.")
            image_to_load = fallback_path
        else:
            return
    else:
        image_to_load = IMAGE_PATH

    print(f"Loading image from {image_to_load}...")
    with open(image_to_load, "rb") as image_file:
        encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
    
    base64_image = f"data:image/jpeg;base64,{encoded_string}"
    print(f"Starting load test: {total_reqs} total requests, {concurrent_reqs} concurrent workers.")
    
    stats = {'success': 0, 'failed': 0}
    start_time = time.time()
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrent_reqs) as executor:
        futures = {executor.submit(send_request, i, base64_image): i for i in range(1, total_reqs + 1)}
        for future in concurrent.futures.as_completed(futures):
            try:
                success = future.result()
                if success:
                    stats['success'] += 1
                else:
                    stats['failed'] += 1
            except Exception:
                stats['failed'] += 1

    total_time = time.time() - start_time
    print("\n" + "="*40)
    print("LOAD TEST RESULTS")
    print("="*40)
    print(f"Total time : {total_time:.2f} seconds")
    print(f"Total reqs : {total_reqs}")
    print(f"Successful : {stats['success']}")
    print(f"Failed     : {stats['failed']}")
    if total_time > 0:
        print(f"Reqs/sec   : {total_reqs / total_time:.2f}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nTest cancelled by user.")
