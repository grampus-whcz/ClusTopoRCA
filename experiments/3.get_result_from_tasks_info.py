import re
import csv
import json
from collections import defaultdict

# 配置路径
file_path = "/root/shared-nvme/work/agent/OpenRCA/experiments/Bank/claude-3-5-sonnet-20241022/Bank_all_RAG_claude-3-5-sonnet-20241022_extracted_tasks_info.md"
task_csv = "/root/shared-nvme/work/agent/OpenRCA/experiments/Bank/claude-3-5-sonnet-20241022/Bank_all_RAG_claude-3-5-sonnet-20241022_task_summary.csv"
global_csv = "/root/shared-nvme/work/agent/OpenRCA/experiments/Bank/claude-3-5-sonnet-20241022/Bank_all_RAG_claude-3-5-sonnet-20241022_global_summary.csv"

# Patterns
token_pattern = re.compile(r'==claude-3-5-sonnet-20241022=====================input Tokens: (\d+), output Tokens: (\d+)')
score_pattern = re.compile(r"Candidate \d+: Score: ([\d.]+)")
task_line_pattern = re.compile(r'^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}.*task_\d+')

tasks = defaultdict(lambda: {'input_tokens': 0, 'output_tokens': 0, 'scores': []})
current_task = None

with open(file_path, 'r', encoding='utf-8') as f:
    for line in f:
        stripped = line.strip()

        if task_line_pattern.match(stripped):
            current_task = stripped
            continue

        if current_task is None:
            continue

        m = token_pattern.search(line)
        if m:
            tasks[current_task]['input_tokens'] += int(m.group(1))
            tasks[current_task]['output_tokens'] += int(m.group(2))
            continue

        m = score_pattern.search(line)
        if m:
            tasks[current_task]['scores'].append(float(m.group(1)))

# 准备任务级数据
task_rows = []
all_scores = []
total_pseudo_solved_tasks = 0  # 原solved_task_count，改名为伪解决数
total_actual_solved_tasks = 0   # 新增：有至少1个满分候选的任务数
total_partial_actual_solved_tasks = 0  # 新增：只有0-1分（不含1）的任务数

# 新增：用于全局统计的变量
sum_max_scores = 0.0    # Max Score 的总和
sum_avg_scores = 0.0    # Avg Score 的总和
sum_pseudo_scores = 0.0 # Sum Score 的伪总和（超过1按1算）

print("\n" + "="*80)
print("📊 TASK-BY-TASK SUMMARY")
print("="*80)

for task_id, stats in tasks.items():
    input_t = stats['input_tokens']
    output_t = stats['output_tokens']
    total_t = input_t + output_t
    scores = stats['scores']
    num_candidates = len(scores)
    
    # === 统计 perfect candidates (score == 1.0) ===
    perfect_candidates = [s for s in scores if abs(s - 1.0) < 1e-6]  # 容忍浮点误差
    num_perfect = len(perfect_candidates)
    
    # 1. 伪解决数：有几个满分候选就计数几次（原逻辑）
    total_pseudo_solved_tasks += num_perfect
    
    # 2. 实际解决数：只要有至少1个满分候选，计1次
    is_actually_solved = num_perfect >= 1
    if is_actually_solved:
        total_actual_solved_tasks += 1
    
    # 3. 部分解决数：没有满分候选，但有0-1之间的分数
    partial_scores = [s for s in scores if 0 < s < 1]
    is_partially_solved = (num_perfect == 0) and (len(partial_scores) > 0)
    if is_partially_solved:
        total_partial_actual_solved_tasks += 1

    max_score = max(scores) if scores else 0.0
    avg_score = sum(scores) / num_candidates if num_candidates > 0 else 0.0
    sum_score = sum(scores)
    
    # 计算当前任务的伪sum score（超过1按1算）
    pseudo_sum_score = min(sum(scores), 1.0)
    
    all_scores.extend(scores)

    row = {
        'task_id': task_id,
        'input_tokens': input_t,
        'output_tokens': output_t,
        'total_tokens': total_t,
        'num_candidates': num_candidates,
        'num_perfect_candidates': num_perfect,
        'is_actually_solved': is_actually_solved,       # 新增：是否实际解决（有满分）
        'is_partially_solved': is_partially_solved,     # 新增：是否部分解决（无满分但有0-1分）
        'max_score': round(max_score, 6),
        'avg_score': round(avg_score, 6),
        'sum_score': round(sum_score, 6),
        'pseudo_sum_score': round(pseudo_sum_score, 6),
        'all_scores': json.dumps(scores)
    }
    task_rows.append(row)
    
    # 累加至全局统计变量
    sum_max_scores += max_score
    sum_avg_scores += avg_score
    sum_pseudo_scores += pseudo_sum_score

    # 打印到终端
    print(f"\n🔹 Task: {task_id}")
    print(f"   Input Tokens:           {input_t:,}")
    print(f"   Output Tokens:          {output_t:,}")
    print(f"   Total Tokens:           {total_t:,}")
    print(f"   Candidates:             {num_candidates}")
    print(f"   Perfect (score=1.0):    {num_perfect}")
    print(f"   Is Actually Solved:     {'✅ Yes' if is_actually_solved else '❌ No'}")
    print(f"   Is Partially Solved:    {'✅ Yes' if is_partially_solved else '❌ No'}")
    print(f"   Scores:                 {scores}")
    print(f"   Max Score:              {max_score:.6f}")
    print(f"   Avg Score:              {avg_score:.6f}")
    print(f"   Sum Score:              {sum_score:.6f}")
    print(f"   Pseudo Sum Score:       {pseudo_sum_score:.6f}")

# 全局统计
total_tasks = len(task_rows)
total_input = sum(row['input_tokens'] for row in task_rows)
total_output = sum(row['output_tokens'] for row in task_rows)
total_tokens = total_input + total_output
total_candidates = len(all_scores)
total_score_sum = sum(all_scores)
global_avg_score = total_score_sum / total_candidates if total_candidates > 0 else 0.0

# 新增：总解决数 = 实际解决数 + 部分解决数
total_solved_tasks = total_actual_solved_tasks + total_partial_actual_solved_tasks

# 各类解决率计算
actual_correct_rate = (total_actual_solved_tasks / total_tasks * 100) if total_tasks > 0 else 0.0
partial_correct_rate = (total_partial_actual_solved_tasks / total_tasks * 100) if total_tasks > 0 else 0.0
total_correct_rate = (total_solved_tasks / total_tasks * 100) if total_tasks > 0 else 0.0

# 构建全局统计行（更新统计项）
global_row = {
    'total_tasks': total_tasks,
    'total_pseudo_solved_tasks': total_pseudo_solved_tasks,  # 原solved_task_count改名
    'total_actual_solved_tasks': total_actual_solved_tasks,  # 新增
    'total_partial_actual_solved_tasks': total_partial_actual_solved_tasks,  # 新增
    'total_solved_tasks': total_solved_tasks,  # 新增：实际+部分
    'actual_correct_rate_percent': round(actual_correct_rate, 4),  # 新增
    'partial_correct_rate_percent': round(partial_correct_rate, 4),  # 新增
    'total_correct_rate_percent': round(total_correct_rate, 4),  # 新增
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

# 打印全局汇总（更新统计项）
print("\n" + "="*80)
print("📈 GLOBAL SUMMARY")
print("="*80)
print(f"Total Tasks:                {total_tasks}")
print(f"Total Pseudo Solved Tasks:  {total_pseudo_solved_tasks} (按满分候选数计数)")
print(f"Total Actual Solved Tasks:  {total_actual_solved_tasks} (有至少1个满分候选)")
print(f"Total Partial Solved Tasks: {total_partial_actual_solved_tasks} (无满分但有0-1分)")
print(f"Total Solved Tasks:         {total_solved_tasks} (实际+部分)")
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

# 保存 task_summary.csv
with open(task_csv, 'w', newline='', encoding='utf-8') as f:
    if task_rows:
        writer = csv.DictWriter(f, fieldnames=task_rows[0].keys())
        writer.writeheader()
        writer.writerows(task_rows)

# 保存 global_summary.csv
with open(global_csv, 'w', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=global_row.keys())
    writer.writeheader()
    writer.writerow(global_row)

print(f"\n✅ Results saved to:")
print(f"   - Task-level:   {task_csv}")
print(f"   - Global-level: {global_csv}")