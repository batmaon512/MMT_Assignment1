import csv
import matplotlib.pyplot as plt


def plot_benchmark(csv_file='benchmark_servers.csv'):
    # Initialize dictionary to store data by Mode
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
        print(f"❌ Could not find file {csv_file}. Run benchmark_all.py first!")
        return

    # Configure colors and line styles for each Mode
    styles = {
        'Threading': {'color': '#1f77b4', 'marker': 'o'},  # Blue
        'Callback': {'color': '#2ca02c', 'marker': 's'},   # Green
        'Asyncio': {'color': '#d62728', 'marker': '^'}     # Red
    }

    # Initialize plot space: 2 subplots arranged vertically
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 10))

    # --- CHART 1: THROUGHPUT (RPS) ---
    for mode in data_concurrency.keys():
        ax1.plot(
            data_concurrency[mode], data_rps[mode],
            label=mode,
            color=styles.get(mode, {}).get('color', 'black'),
            marker=styles.get(mode, {}).get('marker', 'x'),
            linewidth=2, markersize=6
        )
    ax1.set_title('Throughput (RPS) by Concurrency Level',
                  fontsize=14, fontweight='bold', pad=15)
    ax1.set_xlabel(
        'Concurrency (Number of concurrent connections)', fontsize=12)
    ax1.set_ylabel('RPS (Requests Per Second)', fontsize=12)
    ax1.grid(True, linestyle='--', alpha=0.6)
    ax1.legend(title='Architecture', fontsize=11)

    # --- CHART 2: LATENCY ---
    for mode in data_concurrency.keys():
        ax2.plot(
            data_concurrency[mode], data_latency[mode],
            label=mode,
            color=styles.get(mode, {}).get('color', 'black'),
            marker=styles.get(mode, {}).get('marker', 'x'),
            linewidth=2, markersize=6
        )
    ax2.set_title('Average Latency by Concurrency Level',
                  fontsize=14, fontweight='bold', pad=15)
    ax2.set_xlabel(
        'Concurrency (Number of concurrent connections)', fontsize=12)
    ax2.set_ylabel('Average Latency (ms)', fontsize=12)
    ax2.grid(True, linestyle='--', alpha=0.6)
    ax2.legend(title='Architecture', fontsize=11)

    # Adjust layout to prevent text overlap
    plt.tight_layout(pad=3.0)

    # Save image and display
    output_img = 'benchmark_charts.png'
    plt.savefig(output_img, dpi=300, bbox_inches='tight')
    print(f"✅ Successfully saved chart to file: {output_img}")

    print("Opening chart display window...")
    plt.show()


if __name__ == '__main__':
    try:
        import matplotlib
    except ImportError:
        print("❌ matplotlib library is not installed.")
        print("💡 Run this command in Terminal first:")
        print("    pip install matplotlib")
        import sys
        sys.exit(1)

    plot_benchmark()
