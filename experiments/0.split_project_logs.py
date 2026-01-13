import os
import re

def sanitize_filename(filename):
    """
    清理文件名中的非法字符，将其替换为安全的短横线(-)
    非法字符包括：/ \ : * ? " < > |
    
    Args:
        filename: 原始文件名/项目名
    
    Returns:
        清理后的安全文件名
    """
    # 定义需要替换的非法字符正则模式
    illegal_chars = r'[\\/:*?"<>|]'
    # 将非法字符替换为短横线
    sanitized_name = re.sub(illegal_chars, '-', filename)
    # 去除连续的短横线，避免出现多个-连在一起的情况
    sanitized_name = re.sub(r'-+', '-', sanitized_name)
    # 去除首尾的短横线
    sanitized_name = sanitized_name.strip('-')
    return sanitized_name

def split_project_logs(source_log_path, output_dir=None):
    """
    将包含多项目的日志文件按项目分割，每个项目保存为独立的日志文件
    关键识别行格式：包含 "Using dataset: {项目名}" 的行
    自动处理项目名中的非法文件名字符
    
    Args:
        source_log_path: 源日志文件路径
        output_dir: 输出目录（默认使用源文件所在目录）
    """
    # 设置输出目录
    if output_dir is None:
        output_dir = os.path.dirname(source_log_path)
    
    # 确保输出目录存在
    os.makedirs(output_dir, exist_ok=True)
    
    # 源文件名前缀（去除扩展名）
    source_filename = os.path.basename(source_log_path)
    name_prefix = os.path.splitext(source_filename)[0]
    
    # 存储各项目的日志内容
    project_logs = {}
    # 存储原始项目名和清理后文件名的映射，方便核对
    project_name_mapping = {}
    current_project = None
    
    try:
        # 逐行读取日志文件
        with open(source_log_path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                # 去除行尾换行符，保留原始内容
                line_stripped = line.rstrip('\n')
                
                # 检查是否是项目开始行
                if 'Using dataset:' in line_stripped:
                    # 提取项目名称
                    try:
                        # 分割出 "Using dataset: {项目名}" 中的项目名
                        original_project_name = line_stripped.split('Using dataset:')[-1].strip()
                        # 清理项目名中的非法字符，用于文件名
                        sanitized_project_name = sanitize_filename(original_project_name)
                        
                        # 如果清理后的项目名为空（极端情况），用默认名称
                        if not sanitized_project_name:
                            sanitized_project_name = f"unknown_project_{len(project_logs)+1}"
                        
                        # 记录映射关系
                        project_name_mapping[original_project_name] = sanitized_project_name
                        # 更新当前项目
                        current_project = original_project_name
                        
                        # 如果是新项目，初始化列表（保留重复项目的日志）
                        if current_project not in project_logs:
                            project_logs[current_project] = []
                            
                    except Exception as e:
                        print(f"⚠️ 警告：第 {line_num} 行解析项目名失败 - {e}")
                        print(f"   行内容：{line_stripped}")
                        current_project = None
                
                # 将当前行添加到对应项目的日志中（包括项目开始行本身）
                if current_project is not None:
                    project_logs[current_project].append(line)
        
        # 将每个项目的日志写入独立文件
        for original_name, log_lines in project_logs.items():
            # 获取清理后的项目名
            sanitized_name = project_name_mapping[original_name]
            # 构建输出文件名：BMT_all_RAG_gpt-4o_{清理后的项目名}.log
            output_filename = f"{name_prefix}_{sanitized_name}.log"
            output_path = os.path.join(output_dir, output_filename)
            
            # 写入文件（保留原始换行符）
            with open(output_path, 'w', encoding='utf-8') as f:
                f.writelines(log_lines)
            
            print(f"✅ 成功生成项目日志文件：")
            print(f"   原始项目名：{original_name}")
            print(f"   输出文件名：{output_path}")
            print(f"   日志行数：{len(log_lines)}")
            print("-" * 80)
        
        # 总结信息
        print(f"\n📊 日志分割完成！")
        print(f"   源文件：{source_log_path}")
        print(f"   识别到 {len(project_logs)} 个项目")
        print(f"   输出目录：{output_dir}")
        
        # 输出项目名映射表，方便核对
        if project_name_mapping:
            print(f"\n🔍 项目名-文件名映射表：")
            for original, sanitized in project_name_mapping.items():
                print(f"   {original} → {sanitized}")
        
    except FileNotFoundError:
        print(f"❌ 错误：找不到源文件 {source_log_path}")
    except PermissionError:
        print(f"❌ 错误：没有文件读写权限，请检查权限设置")
    except Exception as e:
        print(f"❌ 发生未知错误：{e}")

# 配置文件路径
source_log_file = "/root/shared-nvme/work/agent/OpenRCA/experiments/BMT/BMT_all_RAG_qwen3-235b-a22b-instruct-2507.log"
# 输出目录可选，默认使用源文件所在目录
output_directory = "/root/shared-nvme/work/agent/OpenRCA/experiments/BMT/"

# 执行日志分割
if __name__ == "__main__":
    split_project_logs(source_log_file, output_directory)