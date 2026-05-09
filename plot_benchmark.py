import csv
import matplotlib.pyplot as plt

def plot_benchmark(csv_file='benchmark_servers.csv'):
    # Khởi tạo từ điển lưu trữ dữ liệu theo từng Mode
    data_concurrency = {}
    data_rps = {}
    data_latency = {}

    try:
        with open(csv_file, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                mode = row['Mode']
                c = int(row['Concurrency'])
                r = float(row['RPS'])
                l = float(row['Avg_ms'])

                if mode not in data_concurrency:
                    data_concurrency[mode] = []
                    data_rps[mode] = []
                    data_latency[mode] = []

                data_concurrency[mode].append(c)
                data_rps[mode].append(r)
                data_latency[mode].append(l)
    except FileNotFoundError:
        print(f"❌ Không tìm thấy file {csv_file}. Hãy chạy benchmark_all.py trước!")
        return

    # Cấu hình màu sắc và định dạng nét vẽ cho từng Mode
    styles = {
        'Threading': {'color': '#1f77b4', 'marker': 'o'},  # Xanh dương
        'Callback': {'color': '#2ca02c', 'marker': 's'},   # Xanh lá
        'Asyncio': {'color': '#d62728', 'marker': '^'}     # Đỏ
    }

    # Khởi tạo không gian vẽ: 2 đồ thị con xếp dọc
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 10))

    # --- ĐỒ THỊ 1: THÔNG LƯỢNG (RPS) ---
    for mode in data_concurrency.keys():
        ax1.plot(
            data_concurrency[mode], data_rps[mode], 
            label=mode, 
            color=styles.get(mode, {}).get('color', 'black'),
            marker=styles.get(mode, {}).get('marker', 'x'),
            linewidth=2, markersize=6
        )
    ax1.set_title('Thông lượng (RPS) theo Mức độ Đồng thời', fontsize=14, fontweight='bold', pad=15)
    ax1.set_xlabel('Concurrency (Số kết nối đồng thời)', fontsize=12)
    ax1.set_ylabel('RPS (Requests Per Second)', fontsize=12)
    ax1.grid(True, linestyle='--', alpha=0.6)
    ax1.legend(title='Architecture', fontsize=11)

    # --- ĐỒ THỊ 2: ĐỘ TRỄ (LATENCY) ---
    for mode in data_concurrency.keys():
        ax2.plot(
            data_concurrency[mode], data_latency[mode], 
            label=mode, 
            color=styles.get(mode, {}).get('color', 'black'),
            marker=styles.get(mode, {}).get('marker', 'x'),
            linewidth=2, markersize=6
        )
    ax2.set_title('Độ trễ Trung bình (Avg Latency) theo Mức độ Đồng thời', fontsize=14, fontweight='bold', pad=15)
    ax2.set_xlabel('Concurrency (Số kết nối đồng thời)', fontsize=12)
    ax2.set_ylabel('Average Latency (ms)', fontsize=12)
    ax2.grid(True, linestyle='--', alpha=0.6)
    ax2.legend(title='Architecture', fontsize=11)

    # Căn chỉnh layout tránh dính chữ
    plt.tight_layout(pad=3.0)

    # Lưu ảnh và hiển thị
    output_img = 'benchmark_charts.png'
    plt.savefig(output_img, dpi=300, bbox_inches='tight')
    print(f"✅ Đã lưu biểu đồ sắc nét thành công vào file: {output_img}")
    
    print("Đang mở cửa sổ hiển thị biểu đồ...")
    plt.show()

if __name__ == '__main__':
    try:
        import matplotlib
    except ImportError:
        print("❌ Hệ thống chưa cài đặt thư viện matplotlib để vẽ biểu đồ.")
        print("💡 Hãy chạy lệnh này trong Terminal trước:")
        print("    pip install matplotlib")
        import sys
        sys.exit(1)

    plot_benchmark()
