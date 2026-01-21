# 定义路径
src_path = "/root/shared-nvme/work/agent/OpenRCA/experiments/Market/glm-4.6/Market_cloudbed-2_all_RAG_glm-4.6.log"
dst_path = "/root/shared-nvme/work/agent/OpenRCA/experiments/Market/glm-4.6/Market_cloudbed-2_all_RAG_glm-4.6_8_77.log"

# 读取源文件内容
with open(src_path, 'r', encoding='utf-8') as f:
    src_content = f.read()

# 读取目标文件原有内容（如果文件不存在，则视为空）
try:
    with open(dst_path, 'r', encoding='utf-8') as f:
        dst_content = f.read()
except FileNotFoundError:
    dst_content = ""

# 构造新内容：源内容前加一个空行，然后接原目标文件内容
# 注意：这里“在源内容前加一个空行” → 即 '\n' + src_content
# 然后整体放在原目标内容前面
new_content = '\n' + src_content + dst_content

# 写回目标文件（覆盖原文件）
with open(dst_path, 'w', encoding='utf-8') as f:
    f.write(new_content)