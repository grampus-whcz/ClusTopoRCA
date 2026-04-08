import re
import os
from pathlib import Path

def extract_task_info(input_file, model_name):
    """
    提取任务信息，支持动态传入模型名称以匹配对应的日志行
    
    Args:
        input_file: 输入日志文件路径
        model_name: 大模型名称，用于匹配对应的token行
    Returns:
        提取的任务信息列表
    """
    # 匹配任务头：例如 "2025-12-14_07-53-13_#41-0: task_1"
    task_header_pattern = re.compile(r'^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_#\d+-\d+:\s*task_\d+$')
    
    # 动态生成token匹配模式，适配不同的模型名称
    # 转义模型名称中的特殊字符（如:、.、-等）以避免正则表达式冲突
    escaped_model_name = re.escape(model_name)
    # token_pattern = re.compile(
    #     r'\|\s*INFO\s+\|\s*rca\.api_router:AI_chat_completion:\d+\s*-\s*==' 
    #     + escaped_model_name 
    #     + r'=====================input Tokens:'
    # )
    
    token_pattern = re.compile(
        r'\|\s*INFO\s+\|\s*rca\.api_router:GLM_chat_completion:\d+\s*-\s*==' 
        + escaped_model_name 
        + r'=====================input Tokens:'
    )

    scoring_patterns = {
        'scoring': re.compile(r'\|\s*INFO\s+\|\s*__main__:main:\d+\s*-\s*Candidate \d+:\s*Scoring Points:'),
        'passed': re.compile(r'\|\s*INFO\s+\|\s*__main__:main:\d+\s*-\s*Candidate \d+:\s*Passed Criteria:'),
        'failed': re.compile(r'\|\s*INFO\s+\|\s*__main__:main:\d+\s*-\s*Candidate \d+:\s*Failed Criteria:'),
        'score':  re.compile(r'\|\s*INFO\s+\|\s*__main__:main:\d+\s*-\s*Candidate \d+:\s*Score:'),
    }

    extracted_tasks = []
    current_task_id = None
    current_lines = []

    # 处理文件不存在的情况
    if not os.path.exists(input_file):
        print(f"警告：文件 {input_file} 不存在，跳过处理")
        return extracted_tasks

    with open(input_file, 'r', encoding='utf-8') as f:
        for line in f:
            stripped_line = line.rstrip()

            # 检测任务头（独立一行，无#）
            if task_header_pattern.match(stripped_line):
                # 保存上一个任务
                if current_task_id is not None:
                    extracted_tasks.append({
                        'task_id': current_task_id,
                        'lines': current_lines.copy()
                    })
                # 开始新任务
                current_task_id = stripped_line
                current_lines = []
                continue

            # 如果当前在某个任务上下文中
            if current_task_id is not None:
                # 匹配 token 行
                if token_pattern.search(stripped_line):
                    current_lines.append(stripped_line)
                else:
                    # 匹配评分相关行
                    for key, pattern in scoring_patterns.items():
                        if pattern.search(stripped_line):
                            current_lines.append(stripped_line)
                            break  # 避免重复添加

        # 保存最后一个任务
        if current_task_id is not None:
            extracted_tasks.append({
                'task_id': current_task_id,
                'lines': current_lines
            })

    return extracted_tasks


def write_to_output_file(tasks, output_file):
    """
    将提取的任务信息写入输出文件
    
    Args:
        tasks: 提取的任务信息列表
        output_file: 输出文件路径
    """
    # 确保输出目录存在
    output_dir = os.path.dirname(output_file)
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        for task in tasks:
            f.write('#' * 80 + '\n')
            f.write(task['task_id'] + '\n')
            f.write('#' * 80 + '\n')
            for line in task['lines']:
                f.write(line + '\n')
            f.write('\n')  # 任务之间空一行


def process_all_combinations(base_path):
    """
    处理所有数据集和模型的组合，修正Market数据集的文件名生成逻辑
    
    Args:
        base_path: 基础路径（experiments目录的路径）
    """
    # 配置所有数据集：key=主目录名，value=(子数据集列表, 文件名前缀)
    datasets = {
        'Bank': (['Bank'], 'Bank'),
        'Market': (['Market_cloudbed-1', 'Market_cloudbed-2'], '{sub_dataset}'),  # 使用子数据集名称作为文件名前缀
        'Telecom': (['Telecom'], 'Telecom')
    }
    
    # ablation
    # datasets = {
    #     'ablation': (['Bank'], 'Bank'),
    #     # 'ablation': (['Market_cloudbed-1', 'Market_cloudbed-2'], '{sub_dataset}'),  # 使用子数据集名称作为文件名前缀
    #     # 'ablation': (['Telecom'], 'Telecom')
    # }
    
    # 配置所有大模型名称
    llm_models = [
        # 'glm-4.5',
        # 'glm-4.6',
        # 'glm-4.7',
        # 'claude-3-5-sonnet-20241022',
        # 'deepseek-r1-250528',
        # 'deepseek-r1-0528',
        # 'gemini-2.5-pro-preview-p',
        'gpt-4o',
        # 'llama3.1:8b-instruct-q8_0',
        # 'qwen3-235b-a22b-instruct-2507'
    ]
    
    # 遍历所有数据集
    for dataset_main, (dataset_subs, filename_prefix_pattern) in datasets.items():
        for dataset_sub in dataset_subs:
            # 生成文件名前缀（Market使用子数据集名称，其他使用主数据集名称）
            filename_prefix = filename_prefix_pattern.format(sub_dataset=dataset_sub)
            
            # 遍历所有模型
            for model in llm_models:
                # 构建输入文件路径
                # input_filename = f"{filename_prefix}_all_RAG_{model}.log"
                input_filename = f"{filename_prefix}_no_RAG_c3_knowledge_graph_advanced_merged_{model}.log"
                input_path = os.path.join(
                    base_path, 
                    dataset_main,  # 目录仍使用主数据集名称（Market）
                    model, 
                    input_filename
                )
                
                # 构建输出文件路径
                # output_filename = f"{filename_prefix}_all_RAG_{model}_extracted_tasks_info.md"
                output_filename = f"{filename_prefix}_no_RAG_c3_knowledge_graph_advanced_merged_{model}_extracted_tasks_info.md"
                output_path = os.path.join(
                    base_path, 
                    dataset_main, 
                    model, 
                    output_filename
                )
                
                # 提取任务信息
                print(f"正在处理: {input_path}")
                tasks = extract_task_info(input_path, model)
                
                # 写入输出文件
                if tasks:
                    write_to_output_file(tasks, output_path)
                    print(f"成功提取 {len(tasks)} 个任务，结果已写入 {output_path}")
                else:
                    print(f"未提取到任何任务，跳过写入: {output_path}")
                
                print("-" * 80)


if __name__ == '__main__':
    # 配置基础路径（experiments目录）
    BASE_PATH = '/root/shared-nvme/work/agent/OpenRCA/experiments'
    
    # 执行批量处理
    process_all_combinations(BASE_PATH)
    
    print("所有数据集和模型处理完成！")