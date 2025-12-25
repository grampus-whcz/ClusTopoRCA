import os
import json
import pandas as pd
from glob import glob

# 配置路径
json_dir_path = '/root/shared-nvme/work/agent/OpenRCA/tokens_num/deepseek-r1-0528'
output_csv_file = 'deepseek-r1-0528_output.csv'

def load_json_files(directory):
    """加载目录下所有 JSON 文件中的 data 列表"""
    all_data = []
    for file_path in glob(os.path.join(directory, '*.json')):
        with open(file_path, 'r', encoding='utf-8') as f:
            content = json.load(f)
            all_data.extend(content.get('data', []))
    return all_data

def remove_duplicates(data_list):
    """根据 'id' 去重，保留首次出现的记录"""
    seen = set()
    unique = []
    for item in data_list:
        record_id = item.get('id')
        if record_id is not None and record_id not in seen:
            seen.add(record_id)
            unique.append(item)
    return unique

def save_to_csv(data_list, output_file):
    """将数据保存为 CSV（覆盖模式）"""
    df = pd.DataFrame(data_list)
    # 显式使用 'w' 模式并写入 header，确保每次都是全新文件
    df.to_csv(output_file, index=False, mode='w', header=True)

def calculate_and_print_stats(data_list):
    """计算并打印统计信息"""
    if not data_list:
        print("No data to calculate statistics.")
        return

    df = pd.DataFrame(data_list)
    total_records = len(df)

    sum_prompt = df['promptTokens'].sum()
    sum_completion = df['completionTokens'].sum()
    sum_total = df['totalTokens'].sum()
    sum_cost = df['cost'].sum()

    avg_prompt = df['promptTokens'].mean()
    avg_completion = df['completionTokens'].mean()
    avg_total = df['totalTokens'].mean()
    avg_cost = df['cost'].mean()

    print("\n📊 Statistics:")
    print(f"Total records: {total_records}")
    print(f"promptTokens   → Sum: {sum_prompt:>12}, Avg: {avg_prompt:>12.2f}")
    print(f"completionTokens → Sum: {sum_completion:>12}, Avg: {avg_completion:>12.2f}")
    print(f"totalTokens      → Sum: {sum_total:>12}, Avg: {avg_total:>12.2f}")
    print(f"cost             → Sum: {sum_cost:>12.6f}, Avg: {avg_cost:>12.6f}")

def main():
    print("Loading JSON files...")
    data = load_json_files(json_dir_path)
    print(f"Loaded {len(data)} records (before deduplication).")

    unique_data = remove_duplicates(data)
    print(f"Deduplicated to {len(unique_data)} unique records.")

    print("Saving to CSV (overwriting if exists)...")
    save_to_csv(unique_data, output_csv_file)

    print(f"✅ Data saved to {output_csv_file}")

    # 统计并输出
    calculate_and_print_stats(unique_data)

if __name__ == "__main__":
    main()