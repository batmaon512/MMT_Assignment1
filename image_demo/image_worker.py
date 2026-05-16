import asyncio
import minizmq as zmq
import base64
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

def process_image_task(base64_str, watermark_text):
    try:
        # Giải mã chuỗi Base64 thành byte ảnh
        image_data = base64.b64decode(base64_str)
        img = Image.open(BytesIO(image_data))
        
        # 1. Nén ảnh: Resize nếu lớn hơn 800px
        if img.width > 800:
            ratio = 800 / img.width
            img = img.resize((800, int(img.height * ratio)), Image.Resampling.LANCZOS)
        
        # 2. Đóng dấu watermark
        draw = ImageDraw.Draw(img)
        # Lấy font mặc định, phóng to một chút bằng cách vẽ nhiều lần
        draw.text((20, 20), watermark_text, fill="red")
        draw.text((21, 21), watermark_text, fill="yellow")
        
        # 3. Mã hóa ảnh lại thành Base64 để gửi về Server
        buffer = BytesIO()
        img.convert('RGB').save(buffer, format="JPEG", quality=85)
        result_b64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
        
        return True, result_b64
    except Exception as e:
        return False, str(e)

async def main():
    ctx = zmq.asyncio.Context()
    
    # Kết nối PULL để lấy ảnh (từ cổng 5557 của Server)
    puller = ctx.socket(zmq.PULL)
    puller.connect("tcp://127.0.0.1:5557")
    
    # Kết nối PUSH để trả ảnh (về cổng 5558 của Server)
    pusher = ctx.socket(zmq.PUSH)
    pusher.connect("tcp://127.0.0.1:5558")
    
    print("Worker Xử Lý Ảnh (Pillow) đã sẵn sàng!")
    loop = asyncio.get_running_loop()

    while True:
        msg = await puller.recv_json()
        req_id = msg['request_id']
        base64_str = msg['image']
        text = msg['text']
        
        print(f"\n[Worker] Bắt đầu xử lý ảnh ID: {req_id}...")
        
        # Xử lý tính toán trong một Thread riêng (Tránh làm đơ ZMQ)
        success, result_or_err = await loop.run_in_executor(
            None, process_image_task, base64_str, text
        )
        
        if success:
            await pusher.send_json({"request_id": req_id, "status": "success", "result": result_or_err})
            print(f"[Worker] Đã hoàn thành: {req_id}")
        else:
            await pusher.send_json({"request_id": req_id, "status": "error", "error": result_or_err})
            print(f"[Worker] LỖI tại {req_id}: {result_or_err}")

if __name__ == "__main__":
    asyncio.run(main())
