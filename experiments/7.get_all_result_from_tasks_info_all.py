import re
import csv
import json
import os
from collections import defaultdict
from pathlib import Path

# 定义需要排除的故障编号配置
EXCLUDED_TASK_IDS = {
    'Bank': [51, 48, 112, 71, 88, 70, 68, 72, 86, 47, 45, 65, 53, 52, 57, 54, 62, 60, 133, 0, 1, 2, 107, 8, 3, 13, 16, 9, 12, 6],
    'Market_cloudbed-1': [0, 2, 4, 5, 6, 7, 8, 9, 12, 13, 14, 16, 20, 21, 23, 27, 29, 30, 31, 33, 49, 56],
    'Market_cloudbed-2': [],  # Market cloudbed-2 不排除任何编号
    'Telecom': [2, 5, 8, 12, 17]
}

def extract_task_number(task_id):
    """
    从task_id中提取真实任务编号（#xxx-0 中的xxx）
    适配格式：2026-01-06_21-29-34_#102-0: task_2 -> 提取 102
    """
    # 正则匹配 # 和 -0 之间的数字
    match = re.search(r'#(\d+)-0', task_id)
    if match:
        return int(match.group(1))
    # 提取失败时的降级处理
    print(f"⚠️  警告：无法从task_id '{task_id}' 提取真实任务编号，将保留该任务")
    return -1  # -1 不在任何排除列表中

def analyze_task_data(input_file_path, model_name, output_task_csv, output_global_csv, dataset_sub):
    """
    分析单个任务数据文件，生成统计结果（包含全量和排除指定故障后的统计）
    
    Args:
        input_file_path: 输入的.md文件路径
        model_name: 大模型名称（用于生成正则表达式）
        output_task_csv: 任务级统计输出CSV路径
        output_global_csv: 全局统计输出CSV路径
        dataset_sub: 子数据集名称（如Bank/Market_cloudbed-1/Telecom）
    """
    # 动态生成token匹配正则表达式（适配不同模型）
    escaped_model_name = re.escape(model_name)
    token_pattern = re.compile(
        rf'=={escaped_model_name}=====================input Tokens: (\d+), output Tokens: (\d+)'
    )
    score_pattern = re.compile(r"Candidate \d+: Score: ([\d.]+)")
    task_line_pattern = re.compile(r'^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}.*task_\d+')

    # 检查输入文件是否存在
    if not os.path.exists(input_file_path):
        print(f"\n❌ 错误：输入文件不存在 - {input_file_path}")
        return

    # 1. 解析所有任务数据
    all_tasks = defaultdict(lambda: {'input_tokens': 0, 'output_tokens': 0, 'scores': []})
    current_task = None

    print(f"\n📝 开始分析文件: {input_file_path}")
    with open(input_file_path, 'r', encoding='utf-8') as f:
        for line in f:
            stripped = line.strip()

            if task_line_pattern.match(stripped):
                current_task = stripped
                continue

            if current_task is None:
                continue

            m = token_pattern.search(line)
            if m:
                all_tasks[current_task]['input_tokens'] += int(m.group(1))
                all_tasks[current_task]['output_tokens'] += int(m.group(2))
                continue

            m = score_pattern.search(line)
            if m:
                all_tasks[current_task]['scores'].append(float(m.group(1)))

    # 打印调试信息：确认解析到的任务总数
    print(f"\n🔍 调试信息：解析到的总任务数 = {len(all_tasks)}")
    
    # 2. 筛选排除指定故障后的任务（使用修复后的编号提取逻辑）
    excluded_ids = EXCLUDED_TASK_IDS.get(dataset_sub, [])
    print(f"🔍 调试信息：{dataset_sub} 需要排除的故障编号 = {excluded_ids}")
    
    filtered_tasks = {}
    excluded_task_count = 0  # 统计实际排除的任务数
    retained_task_count = 0   # 统计保留的任务数
    
    for task_id, stats in all_tasks.items():
        task_num = extract_task_number(task_id)
        
        # 核心逻辑：只有真实编号在排除列表中才排除
        if task_num in excluded_ids:
            excluded_task_count += 1
            print(f"🔍 调试：排除任务 {task_id} (真实编号={task_num})")
        else:
            filtered_tasks[task_id] = stats
            retained_task_count += 1
    
    # 打印筛选统计
    print(f"\n📊 筛选统计：")
    print(f"   - 原始任务数：{len(all_tasks)}")
    print(f"   - 排除任务数：{excluded_task_count}")
    print(f"   - 保留任务数：{retained_task_count}")

    # 3. 定义统计函数（复用逻辑）
    def calculate_statistics(tasks_dict, label="全量数据"):
        """计算统计指标"""
        task_rows = []
        all_scores = []
        total_pseudo_solved_tasks = 0
        total_actual_solved_tasks = 0
        total_partial_actual_solved_tasks = 0
        sum_max_scores = 0.0
        sum_avg_scores = 0.0
        sum_pseudo_scores = 0.0

        print(f"\n" + "="*80)
        print(f"📊 {label} - TASK-BY-TASK SUMMARY")
        print("="*80)

        for task_id, stats in tasks_dict.items():
            input_t = stats['input_tokens']
            output_t = stats['output_tokens']
            total_t = input_t + output_t
            scores = stats['scores']
            num_candidates = len(scores)
            
            # 统计满分候选
            perfect_candidates = [s for s in scores if abs(s - 1.0) < 1e-6]
            num_perfect = len(perfect_candidates)
            
            # 各类解决数统计
            total_pseudo_solved_tasks += num_perfect
            is_actually_solved = num_perfect >= 1
            if is_actually_solved:
                total_actual_solved_tasks += 1
            
            partial_scores = [s for s in scores if 0 < s < 1]
            is_partially_solved = (num_perfect == 0) and (len(partial_scores) > 0)
            if is_partially_solved:
                total_partial_actual_solved_tasks += 1

            max_score = max(scores) if scores else 0.0
            avg_score = sum(scores) / num_candidates if num_candidates > 0 else 0.0
            sum_score = sum(scores)
            pseudo_sum_score = min(sum(scores), 1.0)
            
            all_scores.extend(scores)

            row = {
                'task_id': task_id,
                'input_tokens': input_t,
                'output_tokens': output_t,
                'total_tokens': total_t,
                'num_candidates': num_candidates,
                'num_perfect_candidates': num_perfect,
                'is_actually_solved': is_actually_solved,
                'is_partially_solved': is_partially_solved,
                'max_score': round(max_score, 6),
                'avg_score': round(avg_score, 6),
                'sum_score': round(sum_score, 6),
                'pseudo_sum_score': round(pseudo_sum_score, 6),
                'all_scores': json.dumps(scores)
            }
            task_rows.append(row)
            
            # 累加全局统计变量
            sum_max_scores += max_score
            sum_avg_scores += avg_score
            sum_pseudo_scores += pseudo_sum_score

        # 计算全局统计
        total_tasks = len(task_rows)
        total_input = sum(row['input_tokens'] for row in task_rows) if task_rows else 0
        total_output = sum(row['output_tokens'] for row in task_rows) if task_rows else 0
        total_tokens = total_input + total_output
        total_candidates = len(all_scores)
        total_score_sum = sum(all_scores)
        global_avg_score = total_score_sum / total_candidates if total_candidates > 0 else 0.0

        # 总解决数
        total_solved_tasks = total_actual_solved_tasks + total_partial_actual_solved_tasks

        # 各类解决率计算
        actual_correct_rate = (total_actual_solved_tasks / total_tasks * 100) if total_tasks > 0 else 0.0
        partial_correct_rate = (total_partial_actual_solved_tasks / total_tasks * 100) if total_tasks > 0 else 0.0
        total_correct_rate = (total_solved_tasks / total_tasks * 100) if total_tasks > 0 else 0.0
        
        # 新增三个比率字段（小数形式，非百分比）
        total_actual_solved_tasks_rate = round(total_actual_solved_tasks / total_tasks, 6) if total_tasks > 0 else 0.0
        total_partial_actual_solved_tasks_rate = round(total_partial_actual_solved_tasks / total_tasks, 6) if total_tasks > 0 else 0.0
        total_solved_tasks_rate = round(total_solved_tasks / total_tasks, 6) if total_tasks > 0 else 0.0

        # 构建全局统计行（调整字段顺序：三个rate字段移到total_solved_tasks之后）
        global_row = {
            'data_type': label,  # 标识数据类型：全量数据/排除训练集后
            'total_tasks': total_tasks,
            'total_pseudo_solved_tasks': total_pseudo_solved_tasks,
            'total_actual_solved_tasks': total_actual_solved_tasks,
            'total_partial_actual_solved_tasks': total_partial_actual_solved_tasks,
            'total_solved_tasks': total_solved_tasks,
            # 三个rate字段调整到total_solved_tasks之后
            'total_actual_solved_tasks_rate': total_actual_solved_tasks_rate,
            'total_partial_actual_solved_tasks_rate': total_partial_actual_solved_tasks_rate,
            'total_solved_tasks_rate': total_solved_tasks_rate,
            # 百分比字段移到rate字段之后
            'actual_correct_rate_percent': round(actual_correct_rate, 4),
            'partial_correct_rate_percent': round(partial_correct_rate, 4),
            'total_correct_rate_percent': round(total_correct_rate, 4),
            'total_input_tokens': total_input,
            'total_output_tokens': total_output,
            'total_tokens': total_tokens,
            'total_candidates': total_candidates,
            'total_score_sum': round(total_score_sum, 6),
            'sum_max_scores': round(sum_max_scores, 6),
            'sum_avg_scores': round(sum_avg_scores, 6),
            'sum_pseudo_scores': round(sum_pseudo_scores, 6),
            'global_avg_score': round(global_avg_score, 6)
        }

        # 打印全局汇总
        print(f"\n" + "="*80)
        print(f"📈 {label} - GLOBAL SUMMARY")
        print("="*80)
        print(f"Total Tasks:                {total_tasks}")
        print(f"Total Pseudo Solved Tasks:  {total_pseudo_solved_tasks} (按满分候选数计数)")
        print(f"Total Actual Solved Tasks:  {total_actual_solved_tasks} (有至少1个满分候选)")
        print(f"Total Partial Solved Tasks: {total_partial_actual_solved_tasks} (无满分但有0-1分)")
        print(f"Total Solved Tasks:         {total_solved_tasks} (实际+部分)")
        print(f"Actual Solved Rate:         {total_actual_solved_tasks_rate:.6f}")
        print(f"Partial Solved Rate:        {total_partial_actual_solved_tasks_rate:.6f}")
        print(f"Total Solved Rate:          {total_solved_tasks_rate:.6f}")
        print(f"Actual Correct Rate (%):    {actual_correct_rate:.4f}%")
        print(f"Partial Correct Rate (%):   {partial_correct_rate:.4f}%")
        print(f"Total Correct Rate (%):     {total_correct_rate:.4f}%")
        print("-" * 80)
        print(f"Total Candidates:           {total_candidates}")
        print(f"Total Input Tokens:         {total_input:,}")
        print(f"Total Output Tokens:        {output_t:,}")
        print(f"Total Tokens:               {total_tokens:,}")
        print(f"Sum of All Scores:          {total_score_sum:.6f}")
        print(f"Sum of Task Max Scores:     {sum_max_scores:.6f}")
        print(f"Sum of Task Avg Scores:     {sum_avg_scores:.6f}")
        print(f"Sum of Pseudo Scores:       {sum_pseudo_scores:.6f}")
        print(f"Global Average Score:       {global_avg_score:.6f}")
        print("="*80)

        return task_rows, global_row

    # 4. 计算全量数据统计
    all_task_rows, all_global_row = calculate_statistics(all_tasks, "全量数据")
    
    # 5. 计算排除指定故障后的统计
    filtered_task_rows, filtered_global_row = calculate_statistics(filtered_tasks, "排除训练集后")

    # 6. 保存任务级数据（全量）
    Path(os.path.dirname(output_task_csv)).mkdir(parents=True, exist_ok=True)
    with open(output_task_csv, 'w', newline='', encoding='utf-8') as f:
        if all_task_rows:
            writer = csv.DictWriter(f, fieldnames=all_task_rows[0].keys())
            writer.writeheader()
            writer.writerows(all_task_rows)

    # 7. 保存全局统计数据（两行：全量 + 排除后）
    with open(output_global_csv, 'w', newline='', encoding='utf-8') as f:
        # 获取字段名（从全量统计行）
        fieldnames = all_global_row.keys()
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(all_global_row)
        writer.writerow(filtered_global_row)

    print(f"\n✅ Results saved to:")
    print(f"   - Task-level:   {output_task_csv}")
    print(f"   - Global-level: {output_global_csv}")


def process_all_combinations(base_path):
    """
    批量处理所有数据集和模型的组合
    
    Args:
        base_path: 基础路径（experiments目录）
    """
    # 配置数据集：key=主目录名，value=(子数据集列表, 文件名前缀)
    datasets = {
        'Bank': (['Bank'], 'Bank'),
        'Market': (['Market_cloudbed-1', 'Market_cloudbed-2'], '{sub_dataset}'),
        'Telecom': (['Telecom'], 'Telecom')
    }
    
    # 配置所有大模型名称
    llm_models = [
        'glm-4.5',
        'glm-4.6',
        'glm-4.7',
        'claude-3-5-sonnet-20241022',
        'deepseek-r1-250528',
        'gemini-2.5-pro-preview-p',
        'gpt-4o',
        'llama3.1:8b-instruct-q8_0',
        'qwen3-235b-a22b-instruct-2507'
    ]
    
    # 遍历所有数据集
    for dataset_main, (dataset_subs, filename_prefix_pattern) in datasets.items():
        for dataset_sub in dataset_subs:
            # 生成文件名前缀
            filename_prefix = filename_prefix_pattern.format(sub_dataset=dataset_sub)
            
            # 遍历所有模型
            for model in llm_models:
                print(f"\n{'#'*100}")
                print(f"开始处理：数据集={dataset_main}/{dataset_sub} | 模型={model}")
                print(f"{'#'*100}")
                
                # 构建输入文件路径（.md文件）
                input_filename = f"{filename_prefix}_all_RAG_{model}_extracted_tasks_info.md"
                input_path = os.path.join(
                    base_path, 
                    dataset_main, 
                    model, 
                    input_filename
                )
                
                # 构建输出文件路径（.csv文件）
                task_csv_filename = f"{filename_prefix}_all_RAG_{model}_task_summary.csv"
                global_csv_filename = f"{filename_prefix}_all_RAG_{model}_global_summary.csv"
                
                task_csv_path = os.path.join(base_path, dataset_main, model, task_csv_filename)
                global_csv_path = os.path.join(base_path, dataset_main, model, global_csv_filename)
                
                # 执行分析（传入子数据集名称用于筛选排除的故障编号）
                analyze_task_data(input_path, model, task_csv_path, global_csv_path, dataset_sub)
                
                print(f"\n{'='*100}")
                print(f"完成处理：数据集={dataset_main}/{dataset_sub} | 模型={model}")
                print(f"{'='*100}")


if __name__ == '__main__':
    # 配置基础路径（experiments目录）
    BASE_PATH = '/root/shared-nvme/work/agent/OpenRCA/experiments'
    
    # 执行批量处理
    process_all_combinations(BASE_PATH)
    
    print(f"\n🎉 所有数据集和模型处理完成！")
    print(f"基础路径：{BASE_PATH}")