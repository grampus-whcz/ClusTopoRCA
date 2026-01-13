def insert_content_to_file_start(source_file_path, target_file_path):
    """
    将源文件的全部内容插入到目标文件开头，并添加一个换行符
    
    Args:
        source_file_path: 源文件路径（要复制内容的文件）
        target_file_path: 目标文件路径（要插入内容的文件）
    """
    try:
        # 1. 读取源文件的全部内容
        with open(source_file_path, 'r', encoding='utf-8') as source_file:
            source_content = source_file.read()
        
        # 2. 读取目标文件的原有内容
        with open(target_file_path, 'r', encoding='utf-8') as target_file:
            target_content = target_file.read()
        
        # 3. 拼接新内容：源文件内容 + 换行符 + 目标文件原有内容
        new_content = source_content + '\n' + target_content
        
        # 4. 将新内容写回目标文件
        with open(target_file_path, 'w', encoding='utf-8') as target_file:
            target_file.write(new_content)
        
        print(f"成功完成操作！")
        print(f"源文件: {source_file_path}")
        print(f"目标文件: {target_file_path}")
        
    except FileNotFoundError as e:
        print(f"错误：找不到文件 - {e}")
    except PermissionError:
        print(f"错误：没有文件读写权限，请检查文件权限设置")
    except Exception as e:
        print(f"发生未知错误：{e}")

# 定义文件路径
source_file = "/root/shared-nvme/work/agent/OpenRCA/experiments/BMT/BMT_all_RAG_gemini-2.5-pro-preview-p_Bank.log"
target_file = "/root/shared-nvme/work/agent/OpenRCA/experiments/Bank/gemini-2.5-pro-preview-p/Bank_all_RAG_gemini-2.5-pro-preview-p.log"

# 执行操作
if __name__ == "__main__":
    insert_content_to_file_start(source_file, target_file)