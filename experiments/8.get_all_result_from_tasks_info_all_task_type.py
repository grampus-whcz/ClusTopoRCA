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

# 定义任务难度映射
TASK_DIFFICULTY_MAP = {
    1: 'easy',
    2: 'easy',
    3: 'easy',
    4: 'medium',
    5: 'medium',
    6: 'medium',
    7: 'hard'
}

def extract_task_number(task_id):
    """
    从task_id中提取真实任务编号（#xxx-0 中的xxx）
    适配格式：2026-01-06_21-29-34_#102-0: task_2 -> 提取 102
    """
    match = re.search(r'#(\d+)-0', task_id)
    if match:
        return int(match.group(1))
    print(f"⚠️  警告：无法从task_id '{task_id}' 提取真实任务编号，将保留该任务")
    return -1

def extract_task_difficulty(task_id):
    """
    从task_id中提取任务难度类型
    适配格式：2026-01-13_07-49-31_#5-0: task_1 -> 提取 1 -> 映射为 easy
    """
    match = re.search(r'task_(\d+)', task_id)
    if match:
        task_type = int(match.group(1))
        return TASK_DIFFICULTY_MAP.get(task_type, 'unknown')
    print(f"⚠️  警告：无法从task_id '{task_id}' 提取任务类型，标记为 unknown")
    return 'unknown'

def calculate_difficulty_stats(tasks_dict):
    """
    按任务难度分类统计核心指标
    """
    # 初始化难度统计字典
    difficulty_stats = {
        'easy': {'tasks': [], 'total_tasks': 0, 'total_actual_solved': 0, 'total_partial_solved': 0},
        'medium': {'tasks': [], 'total_tasks': 0, 'total_actual_solved': 0, 'total_partial_solved': 0},
        'hard': {'tasks': [], 'total_tasks': 0, 'total_actual_solved': 0, 'total_partial_solved': 0},
        'unknown': {'tasks': [], 'total_tasks': 0, 'total_actual_solved': 0, 'total_partial_solved': 0}
    }
    
    # 遍历所有任务，按难度分类
    for task_id, stats in tasks_dict.items():
        # 获取任务难度
        difficulty = extract_task_difficulty(task_id)
        scores = stats['scores']
        
        # 统计该任务的解决状态
        perfect_candidates = [s for s in scores if abs(s - 1.0) < 1e-6]
        is_actually_solved = len(perfect_candidates) >= 1
        
        partial_scores = [s for s in scores if 0 < s < 1]
        is_partially_solved = (len(perfect_candidates) == 0) and (len(partial_scores) > 0)
        
        # 添加到对应难度分类
        difficulty_stats[difficulty]['tasks'].append({
            'task_id': task_id,
            'is_actually_solved': is_actually_solved,
            'is_partially_solved': is_partially_solved
        })
    
    # 计算各难度的汇总统计
    for diff, stats in difficulty_stats.items():
        task_list = stats['tasks']
        stats['total_tasks'] = len(task_list)
        
        # 统计各类解决数
        stats['total_actual_solved_tasks'] = sum(1 for task in task_list if task['is_actually_solved'])
        stats['total_partial_actual_solved_tasks'] = sum(1 for task in task_list if task['is_partially_solved'])
        stats['total_solved_tasks'] = stats['total_actual_solved_tasks'] + stats['total_partial_actual_solved_tasks']
        
        # 计算比率（小数形式）
        total_tasks = stats['total_tasks']
        if total_tasks > 0:
            stats['total_actual_solved_tasks_rate'] = round(stats['total_actual_solved_tasks'] / total_tasks, 6)
            stats['total_partial_actual_solved_tasks_rate'] = round(stats['total_partial_actual_solved_tasks'] / total_tasks, 6)
            stats['total_solved_tasks_rate'] = round(stats['total_solved_tasks'] / total_tasks, 6)
        else:
            stats['total_actual_solved_tasks_rate'] = 0.0
            stats['total_partial_actual_solved_tasks_rate'] = 0.0
            stats['total_solved_tasks_rate'] = 0.0
    
    return difficulty_stats

def analyze_task_data(input_file_path, model_name, output_task_csv, output_global_csv, output_difficulty_csv, dataset_sub):
    """
    分析单个任务数据文件，生成统计结果（包含全量、排除后、难度分类统计）
    
    Args:
        input_file_path: 输入的.md文件路径
        model_name: 大模型名称
        output_task_csv: 任务级统计输出CSV路径
        output_global_csv: 全局统计输出CSV路径
        output_difficulty_csv: 难度分类统计输出CSV路径
        dataset_sub: 子数据集名称
    """
    # 动态生成token匹配正则表达式
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

    # 打印调试信息
    print(f"\n🔍 调试信息：解析到的总任务数 = {len(all_tasks)}")
    
    # 2. 筛选排除指定故障后的任务
    excluded_ids = EXCLUDED_TASK_IDS.get(dataset_sub, [])
    print(f"🔍 调试信息：{dataset_sub} 需要排除的故障编号 = {excluded_ids}")
    
    filtered_tasks = {}
    excluded_task_count = 0
    retained_task_count = 0
    
    for task_id, stats in all_tasks.items():
        task_num = extract_task_number(task_id)
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

    # 3. 定义通用统计函数
    def calculate_statistics(tasks_dict, label="全量数据"):
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
            
            perfect_candidates = [s for s in scores if abs(s - 1.0) < 1e-6]
            num_perfect = len(perfect_candidates)
            
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
                'task_difficulty': extract_task_difficulty(task_id),  # 新增：任务难度
                'all_scores': json.dumps(scores)
            }
            task_rows.append(row)
            
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

        total_solved_tasks = total_actual_solved_tasks + total_partial_actual_solved_tasks

        actual_correct_rate = (total_actual_solved_tasks / total_tasks * 100) if total_tasks > 0 else 0.0
        partial_correct_rate = (total_partial_actual_solved_tasks / total_tasks * 100) if total_tasks > 0 else 0.0
        total_correct_rate = (total_solved_tasks / total_tasks * 100) if total_tasks > 0 else 0.0
        
        total_actual_solved_tasks_rate = round(total_actual_solved_tasks / total_tasks, 6) if total_tasks > 0 else 0.0
        total_partial_actual_solved_tasks_rate = round(total_partial_actual_solved_tasks / total_tasks, 6) if total_tasks > 0 else 0.0
        total_solved_tasks_rate = round(total_solved_tasks / total_tasks, 6) if total_tasks > 0 else 0.0

        # 构建全局统计行
        global_row = {
            'data_type': label,
            'total_tasks': total_tasks,
            'total_pseudo_solved_tasks': total_pseudo_solved_tasks,
            'total_actual_solved_tasks': total_actual_solved_tasks,
            'total_partial_actual_solved_tasks': total_partial_actual_solved_tasks,
            'total_solved_tasks': total_solved_tasks,
            'total_actual_solved_tasks_rate': total_actual_solved_tasks_rate,
            'total_partial_actual_solved_tasks_rate': total_partial_actual_solved_tasks_rate,
            'total_solved_tasks_rate': total_solved_tasks_rate,
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
        print(f"Total Output Tokens:        {total_output:,}")
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

    # 6. 计算难度分类统计（全量 + 排除后）
    print(f"\n" + "="*80)
    print(f"📊 难度分类统计 - 全量数据")
    print("="*80)
    all_difficulty_stats = calculate_difficulty_stats(all_tasks)
    
    print(f"\n" + "="*80)
    print(f"📊 难度分类统计 - 排除训练集后")
    print("="*80)
    filtered_difficulty_stats = calculate_difficulty_stats(filtered_tasks)

    # 7. 保存任务级数据
    Path(os.path.dirname(output_task_csv)).mkdir(parents=True, exist_ok=True)
    with open(output_task_csv, 'w', newline='', encoding='utf-8') as f:
        if all_task_rows:
            writer = csv.DictWriter(f, fieldnames=all_task_rows[0].keys())
            writer.writeheader()
            writer.writerows(all_task_rows)

    # 8. 保存全局统计数据
    with open(output_global_csv, 'w', newline='', encoding='utf-8') as f:
        fieldnames = all_global_row.keys()
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(all_global_row)
        writer.writerow(filtered_global_row)

    # 9. 保存难度分类统计数据
    difficulty_rows = []
    # 添加全量数据的难度统计
    for diff, stats in all_difficulty_stats.items():
        difficulty_rows.append({
            'data_type': '全量数据',
            'task_difficulty': diff,
            'total_tasks': stats['total_tasks'],
            'total_actual_solved_tasks': stats['total_actual_solved_tasks'],
            'total_partial_actual_solved_tasks': stats['total_partial_actual_solved_tasks'],
            'total_solved_tasks': stats['total_solved_tasks'],
            'total_actual_solved_tasks_rate': stats['total_actual_solved_tasks_rate'],
            'total_partial_actual_solved_tasks_rate': stats['total_partial_actual_solved_tasks_rate'],
            'total_solved_tasks_rate': stats['total_solved_tasks_rate']
        })
    # 添加排除训练集后的难度统计
    for diff, stats in filtered_difficulty_stats.items():
        difficulty_rows.append({
            'data_type': '排除训练集后',
            'task_difficulty': diff,
            'total_tasks': stats['total_tasks'],
            'total_actual_solved_tasks': stats['total_actual_solved_tasks'],
            'total_partial_actual_solved_tasks': stats['total_partial_actual_solved_tasks'],
            'total_solved_tasks': stats['total_solved_tasks'],
            'total_actual_solved_tasks_rate': stats['total_actual_solved_tasks_rate'],
            'total_partial_actual_solved_tasks_rate': stats['total_partial_actual_solved_tasks_rate'],
            'total_solved_tasks_rate': stats['total_solved_tasks_rate']
        })
    
    # 打印难度统计信息
    print(f"\n" + "="*80)
    print(f"📈 难度分类统计汇总")
    print("="*80)
    for row in difficulty_rows:
        print(f"\n{row['data_type']} - {row['task_difficulty'].upper()}：")
        print(f"  总任务数: {row['total_tasks']}")
        print(f"  实际解决数: {row['total_actual_solved_tasks']} ({row['total_actual_solved_tasks_rate']:.6f})")
        print(f"  部分解决数: {row['total_partial_actual_solved_tasks']} ({row['total_partial_actual_solved_tasks_rate']:.6f})")
        print(f"  总解决数: {row['total_solved_tasks']} ({row['total_solved_tasks_rate']:.6f})")

    # 写入难度统计CSV
    with open(output_difficulty_csv, 'w', newline='', encoding='utf-8') as f:
        if difficulty_rows:
            writer = csv.DictWriter(f, fieldnames=difficulty_rows[0].keys())
            writer.writeheader()
            writer.writerows(difficulty_rows)

    print(f"\n✅ Results saved to:")
    print(f"   - Task-level:   {output_task_csv}")
    print(f"   - Global-level: {output_global_csv}")
    print(f"   - Difficulty-level: {output_difficulty_csv}")


def process_all_combinations(base_path):
    """
    批量处理所有数据集和模型的组合
    """
    datasets = {
        'Bank': (['Bank'], 'Bank'),
        # 'Market': (['Market_cloudbed-1', 'Market_cloudbed-2'], '{sub_dataset}'),
        # 'Telecom': (['Telecom'], 'Telecom')
    }
    
    # datasets = {
    #     'ablation': (['Bank'], 'Bank'),
    #     # 'ablation': (['Market_cloudbed-1', 'Market_cloudbed-2'], '{sub_dataset}'),  # 使用子数据集名称作为文件名前缀
    #     # 'ablation': (['Telecom'], 'Telecom')
    # }
    
    llm_models = [
        # 'glm-4.5',
        # 'glm-4.6',
        'glm-4.7',
        # 'claude-3-5-sonnet-20241022',
        # 'deepseek-r1-250528',
        # 'gemini-2.5-pro-preview-p',
        # 'gpt-4o',
        # 'llama3.1:8b-instruct-q8_0',
        # 'qwen3-235b-a22b-instruct-2507'
    ]
    
    # 遍历所有数据集
    for dataset_main, (dataset_subs, filename_prefix_pattern) in datasets.items():
        for dataset_sub in dataset_subs:
            filename_prefix = filename_prefix_pattern.format(sub_dataset=dataset_sub)
            
            # 遍历所有模型
            for model in llm_models:
                print(f"\n{'#'*100}")
                print(f"开始处理：数据集={dataset_main}/{dataset_sub} | 模型={model}")
                print(f"{'#'*100}")
                
                # 构建文件路径
                input_filename = f"{filename_prefix}_no_RAG_c3_knowledge_graph_advanced_merged_0-77_{model}_extracted_tasks_info.md"
                input_path = os.path.join(base_path, dataset_main, model, input_filename)
                
                task_csv_filename = f"{filename_prefix}_no_RAG_c3_knowledge_graph_advanced_merged_0-77_{model}_task_summary.csv"
                global_csv_filename = f"{filename_prefix}_no_RAG_c3_knowledge_graph_advanced_merged_0-77_{model}_global_summary.csv"
                difficulty_csv_filename = f"{filename_prefix}_no_RAG_c3_knowledge_graph_advanced_merged_0-77_{model}_difficulty_summary.csv"
                
                task_csv_path = os.path.join(base_path, dataset_main, model, task_csv_filename)
                global_csv_path = os.path.join(base_path, dataset_main, model, global_csv_filename)
                difficulty_csv_path = os.path.join(base_path, dataset_main, model, difficulty_csv_filename)
                
                # 执行分析
                analyze_task_data(input_path, model, task_csv_path, global_csv_path, difficulty_csv_path, dataset_sub)
                
                print(f"\n{'='*100}")
                print(f"完成处理：数据集={dataset_main}/{dataset_sub} | 模型={model}")
                print(f"{'='*100}")


if __name__ == '__main__':
    BASE_PATH = '/root/shared-nvme/work/agent/OpenRCA/experiments'
    process_all_combinations(BASE_PATH)
    
    print(f"\n🎉 所有数据集和模型处理完成！")
    print(f"基础路径：{BASE_PATH}")