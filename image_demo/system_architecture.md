# Sơ đồ Kiến trúc & Luồng xử lý AsynApRous

Bạn có thể copy mã nguồn `Mermaid` bên dưới và dán trực tiếp vào **Draw.io** bằng cách chọn: **Arrange > Insert > Advanced > Mermaid...**

## 1. Sơ đồ Kiến trúc Tổng thể (Architecture Diagram)
Mô tả các thành phần cấu tạo nên hệ thống và cách chúng liên kết với nhau qua mạng.

```mermaid
graph TD
    Client["Client (load_test.py)"] -- "HTTP POST\n(Base64 Image)" --> Server
    
    subgraph "Trạm Máy Chủ (imageapp.py)"
        Server["HTTP Web Server\n(asyncio + select)"]
        Executor["Task Executor\n(run_in_executor)"]
        ZMQ_PUSH["MiniZMQ PUSH\n(Port 5557)"]
        ZMQ_PULL["MiniZMQ PULL (Collector)\n(Port 5558)"]
        Shared_Dict["SHARED_RESULTS\n(Dict + threading.Event)"]
        
        Server -- "Nhường luồng xử lý" --> Executor
        Executor -- "Lưu chốt chặn (Event)" --> Shared_Dict
        Executor -- "Đẩy task (Non-blocking)" --> ZMQ_PUSH
        ZMQ_PULL -- "Mở chốt chặn (.set)" --> Shared_Dict
    end

    subgraph "Các Trạm Xử Lý (image_worker.py)"
        W1_PULL["Worker 1 PULL\n(I/O Thread)"]
        W1_CPU["CPU ThreadPool\n(Pillow Image Processing)"]
        W1_PUSH["Worker 1 PUSH\n(I/O Thread)"]
        
        W1_PULL -- "Đẩy việc xử lý CPU" --> W1_CPU
        W1_CPU -- "Trả ảnh đã xong" --> W1_PUSH
        
        W2["Worker 2 (Tương tự)"]
        W3["Worker N (Tương tự)"]
    end
    
    ZMQ_PUSH -- "Phân phối TCP\n(Round-Robin)" --> W1_PULL
    ZMQ_PUSH --> W2
    ZMQ_PUSH --> W3
    
    W1_PUSH -- "Nộp báo cáo TCP" --> ZMQ_PULL
    W2 --> ZMQ_PULL
    W3 --> ZMQ_PULL
    
    classDef serverFill fill:#e1f5fe,stroke:#01579b,stroke-width:2px;
    classDef workerFill fill:#fff3e0,stroke:#e65100,stroke-width:2px;
    class Server,Executor,ZMQ_PUSH,ZMQ_PULL,Shared_Dict serverFill;
    class W1_PULL,W1_CPU,W1_PUSH,W2,W3 workerFill;
```

---

## 2. Sơ đồ Trình tự Xử lý (Sequence Diagram)
Mô tả chi tiết vòng đời của 1 Request từ lúc gửi đến lúc nhận, nhấn mạnh vào các cơ chế chống kẹt luồng và kháng lỗi.

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant H as HTTP Server (asyncio)
    participant E as Executor Thread
    participant PUSH as MiniZMQ PUSH
    participant W as Worker Nodes
    participant PULL as MiniZMQ PULL
    
    C->>H: Gửi HTTP POST /images/process (Chứa ảnh)
    H->>E: Chuyển việc sang luồng phụ (run_in_executor)
    note over H,E: Event Loop của Server vẫn rảnh tay<br/>tiếp đón hàng ngàn Client khác!
    
    E->>E: Tạo req_id & threading.Event()
    E->>PUSH: Gửi JSON Task {req_id, image}
    
    PUSH-->>W: Gửi qua mạng TCP (Round-Robin)
    
    note right of PUSH: Nếu Worker mất mạng ngang chừng,<br/>PUSH tự động nhặt ảnh ném cho Worker khác!
    
    E->>E: event.wait(timeout=10.0)
    note over E: Luồng phụ đóng băng (Block)<br/>để chờ kết quả
    
    W->>W: Đưa vào CPU ThreadPool xử lý ảnh
    note right of W: Tách biệt luồng CPU và luồng mạng<br/>chống ThreadPool Starvation
    
    W-->>PULL: Trả kết quả JSON qua TCP
    
    PULL->>PULL: ZMQ Collector nhận kết quả
    PULL->>E: Khớp req_id & Mở chốt (event.set)
    
    note over E: Luồng phụ được đánh thức!
    E->>H: Trả ảnh Base64 đã có Watermark
    H->>C: Phản hồi HTTP 200 OK
```

---

## 3. Sơ đồ Cấu trúc Nội bộ MiniZMQ (MiniZMQ Internals)
Mô tả cách `minizmq.py` hoạt động ở dưới nền (Under the hood) để đảm bảo không chặn luồng (Non-blocking) và không mất dữ liệu.

```mermaid
graph TD
    subgraph "Tầng Ứng dụng (Application Layer)"
        API_Send["send_json(data) / send_json_async(data)"]
        API_Recv["recv_json() / recv_json_async()"]
        Async_Wrapper["Async Context Wrapper\n(run_in_executor)"]
        
        API_Send --> Async_Wrapper
        API_Recv --> Async_Wrapper
    end

    subgraph "MiniZmqSocket (Lõi xử lý)"
        Queue["RAM Queue (HWM=1000)\nChứa tạm các gói tin cần gửi đi"]
        Thread_IO["_io_background_worker\n(Luồng chạy ngầm chuyên I/O Mạng)"]
        Lock["threading.Lock\n(Chống đụng độ RAM)"]
        
        API_Send -- "Nhét task vào (Non-blocking)" --> Queue
        Queue -- "Lấy task ra liên tục" --> Thread_IO
    end

    subgraph "Tầng Mạng TCP (Network Layer)"
        TCP_Send["send_msg(socket, data)"]
        TCP_Recv["recv_msg(socket)"]
        Framing["Custom Framing\n[4-byte Length] + [JSON Payload]"]
        
        Thread_IO -- "Gọi hàm gửi" --> TCP_Send
        TCP_Send <--> Framing
        TCP_Recv <--> Framing
        API_Recv -- "Chặn chờ (Blocking)" --> TCP_Recv
    end
    
    subgraph "Cơ chế Kháng Lỗi (Fault Tolerance)"
        Fail_Catch["Bắt lỗi đứt cáp (Exception)"]
        Requeue["Nhét ngược task bị rớt<br/>vào lại Queue"]
        Reconnect["Tự động gọi connect() lại"]
        
        TCP_Send -. "Lỗi mạng" .-> Fail_Catch
        Fail_Catch -- "Server PUSH" --> Requeue
        Fail_Catch -- "Client PUSH" --> Reconnect
        Requeue -. "Khôi phục dữ liệu" .-> Queue
    end
    
    classDef apiFill fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px;
    classDef coreFill fill:#fff3e0,stroke:#e65100,stroke-width:2px;
    classDef netFill fill:#e3f2fd,stroke:#1565c0,stroke-width:2px;
    classDef faultFill fill:#ffebee,stroke:#c62828,stroke-width:2px,stroke-dasharray: 5 5;
    
    class API_Send,API_Recv,Async_Wrapper apiFill;
    class Queue,Thread_IO,Lock coreFill;
    class TCP_Send,TCP_Recv,Framing netFill;
    class Fail_Catch,Requeue,Reconnect faultFill;
```
