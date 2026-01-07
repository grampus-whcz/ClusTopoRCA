import re

def extract_task_info(input_file):
    # 匹配任务头：例如 "2025-12-14_07-53-13_#41-0: task_1"
    task_header_pattern = re.compile(r'^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_#\d+-\d+:\s*task_\d+$')
    
    # 匹配需要提取的行
    # token_pattern = re.compile(r'\|\s*INFO\s+\|\s*rca\.api_router:AI_chat_completion:\d+\s*-\s*==deepseek-r1-250528=====================input Tokens:')
    token_pattern = re.compile(r'\|\s*INFO\s+\|\s*rca\.api_router:AI_chat_completion:\d+\s*-\s*==deepseek-r1-250528=====================input Tokens:')

    scoring_patterns = {
        'scoring': re.compile(r'\|\s*INFO\s+\|\s*__main__:main:\d+\s*-\s*Candidate \d+:\s*Scoring Points:'),
        'passed': re.compile(r'\|\s*INFO\s+\|\s*__main__:main:\d+\s*-\s*Candidate \d+:\s*Passed Criteria:'),
        'failed': re.compile(r'\|\s*INFO\s+\|\s*__main__:main:\d+\s*-\s*Candidate \d+:\s*Failed Criteria:'),
        'score':  re.compile(r'\|\s*INFO\s+\|\s*__main__:main:\d+\s*-\s*Candidate \d+:\s*Score:'),
    }

    extracted_tasks = []
    current_task_id = None
    current_lines = []

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
    with open(output_file, 'w', encoding='utf-8') as f:
        for task in tasks:
            f.write('#' * 80 + '\n')
            f.write(task['task_id'] + '\n')
            f.write('#' * 80 + '\n')
            for line in task['lines']:
                f.write(line + '\n')
            f.write('\n')  # 任务之间空一行


if __name__ == '__main__':
    input_path = '/root/shared-nvme/work/agent/OpenRCA/experiments/Bank/deepseek-r1-250528/Bank_all_RAG_deepseek-r1-250528.log'
    output_path = '/root/shared-nvme/work/agent/OpenRCA/experiments/Bank/deepseek-r1-250528/Bank_all_RAG_deepseek-r1-250528_extracted_tasks_info.md'

    tasks = extract_task_info(input_path)
    write_to_output_file(tasks, output_path)

    print(f"成功提取 {len(tasks)} 个任务，结果已写入 {output_path}")